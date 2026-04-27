/*
 * This program produces real-time traffic to an external chirpstack server.
 * Key elements are preceded by a comment with lots of dashes ( ///////////// )
 */

#include "elora-example-jammer.h"
#include "elora-example-utilities.h"

// ns3 imports
#include "ns3/constant-position-mobility-model.h"
#include "ns3/core-module.h"
#include "ns3/csma-helper.h"
#include "ns3/internet-stack-helper.h"
#include "ns3/ipv4-address-helper.h"
#include "ns3/ipv4-global-routing-helper.h"
#include "ns3/mobility-helper.h"
#include "ns3/okumura-hata-propagation-loss-model.h"
#include "ns3/propagation-delay-model.h"
#include "ns3/tap-bridge-helper.h"

// lorawan imports
#include "ns3/chirpstack-helper.h"
#include "ns3/hex-grid-position-allocator.h"
#include "ns3/lorawan-helper.h"
#include "ns3/periodic-sender-helper.h"
#include "ns3/range-position-allocator.h"
#include "ns3/udp-forwarder-helper.h"
#include "ns3/urban-traffic-helper.h"

// cpp imports
#include <unordered_map>

using namespace ns3;
using namespace lorawan;

NS_LOG_COMPONENT_DEFINE("EloraExample");

/* Global declaration of connection helper for signal handling */
ChirpStackHelper csHelper;

int
main(int argc, char* argv[])
{
    /***************************
     *  Simulation parameters  *
     ***************************/

    std::string tapName = "ns3-tap";

    std::string tenant = "ELoRa";
    std::string apiAddr = "127.0.0.1";
    uint16_t apiPort = 8090;
    std::string token = "...";
    uint16_t destPort = 1700;

    double periods = 24; // H * D
    bool initializeSF = true;
    bool file = false; // Warning: will produce a file for each gateway
    bool log = false;

    /* Expose parameters to command line */
    {
        CommandLine cmd(__FILE__);
        cmd.AddValue("tapName", "Name of the TAP device created by the simulation.", tapName);
        cmd.AddValue("tenant", "ChirpStack tenant name of this simulation", tenant);
        cmd.AddValue("apiAddr", "ChirpStack REST API endpoint IP address", apiAddr);
        cmd.AddValue("apiPort", "ChirpStack REST API endpoint IP address", apiPort);
        cmd.AddValue("token", "ChirpStack API token (to be generated in ChirpStack UI)", token);
        cmd.AddValue("destPort", "Port used by the ChirpStack Gateway Bridge", destPort);
        cmd.AddValue("periods", "Number of periods to simulate (1 period = 1 hour)", periods);
        cmd.AddValue("initSF", "Whether to initialize the SFs", initializeSF);
        cmd.AddValue("log", "Whether to enable logs", log);
        cmd.Parse(argc, argv);
        if (auto f = getenv("CHIRPSTACK_API_TOKEN_FILE"); f)
        {
            std::ifstream file(f);
            std::getline(file, token);
        }
        NS_ABORT_MSG_IF(token == "...", "Please provide an auth token for the ChirpStack API");
    }

    /* Apply global configurations */
    ///////////////// Real-time operation, necessary to interact with the outside world.
    GlobalValue::Bind("SimulatorImplementationType", StringValue("ns3::RealtimeSimulatorImpl"));
    GlobalValue::Bind("ChecksumEnabled", BooleanValue(true));
    Config::SetDefault("ns3::BaseEndDeviceLorawanMac::EnableCryptography", BooleanValue(true));
    Config::SetDefault("ns3::BaseEndDeviceLorawanMac::FType",
                       EnumValue(LorawanMacHeader::CONFIRMED_DATA_UP));

    /* Logging options */
    if (log)
    {
        //!> Requirement: build ns3 with debug option
        /* Monitor state changes of devices */
        // LogComponentEnable("EloraUtilities", LOG_LEVEL_ALL);
        /* Formatting */
        LogComponentEnableAll(LOG_PREFIX_FUNC);
        LogComponentEnableAll(LOG_PREFIX_NODE);
        LogComponentEnableAll(LOG_PREFIX_TIME);
    }

    /*******************
     *  Radio Channel  *
     *******************/

    Ptr<OkumuraHataPropagationLossModel> loss;
    Ptr<NakagamiPropagationLossModel> rayleigh;
    Ptr<LoraChannel> channel;
    {
        // Delay obtained from distance and speed of light in air
        double refraction = 1.0003;
        auto delay = CreateObject<ConstantSpeedPropagationDelayModel>();
        delay->SetAttribute("Speed", DoubleValue(299792458 / refraction));

        // This one is empirical and it encompasses average loss due to distance, shadowing (i.e.
        // obstacles), weather, height
        loss = CreateObject<OkumuraHataPropagationLossModel>();
        loss->SetAttribute("Frequency", DoubleValue(868100000.0));
        loss->SetAttribute("Environment", EnumValue(UrbanEnvironment));
        loss->SetAttribute("CitySize", EnumValue(LargeCity));

        // Here we can add variance to the propagation model with multipath Rayleigh fading
        rayleigh = CreateObject<NakagamiPropagationLossModel>();
        rayleigh->SetAttribute("m0", DoubleValue(1.0));
        rayleigh->SetAttribute("m1", DoubleValue(1.0));
        rayleigh->SetAttribute("m2", DoubleValue(1.0));

        channel = CreateObject<LoraChannel>(loss, delay);
    }

    /******************
     *  Create Nodes  *
     ******************/

    Ptr<Node> exitnode;
    Ptr<Node> gateway;
    Ptr<Node> endDevice;
    Ptr<Node> jammer;
    {
        exitnode = CreateObject<Node>();

        gateway = CreateObject<Node>();
        auto mobilityGw = CreateObject<ConstantPositionMobilityModel>();
        mobilityGw->SetPosition(Vector(0, 0, 1));
        gateway->AggregateObject(mobilityGw);

        endDevice = CreateObject<Node>();
        auto mobilityEd1 = CreateObject<ConstantPositionMobilityModel>();
        mobilityEd1->SetPosition(Vector(1, 0, 1));
        endDevice->AggregateObject(mobilityEd1);

        jammer = CreateObject<Node>();
        auto mobilityEd2 = CreateObject<ConstantPositionMobilityModel>();
        mobilityEd2->SetPosition(Vector(0, 1, 1));
        jammer->AggregateObject(mobilityEd2);
    }

    /************************
     *  Create Net Devices  *
     ************************/

    /* Csma between gateway and tap-bridge (represented by exitnode) */
    {
        auto csmaNodes = NodeContainer(exitnode, gateway);

        // Connect the bridge to the gateway with csma
        CsmaHelper csma;
        csma.SetChannelAttribute("DataRate", DataRateValue(DataRate(5000000)));
        csma.SetChannelAttribute("Delay", TimeValue(MilliSeconds(2)));
        csma.SetDeviceAttribute("Mtu", UintegerValue(1500));
        auto csmaNetDevs = csma.Install(csmaNodes);

        // Install and initialize internet stack on gateways and bridge nodes
        InternetStackHelper internet;
        internet.Install(csmaNodes);

        Ipv4AddressHelper addresses;
        addresses.SetBase("10.1.2.0", "255.255.255.0");
        addresses.Assign(csmaNetDevs);

        Ipv4GlobalRoutingHelper::PopulateRoutingTables();
    }

    ///////////////// Attach a Tap-bridge to outside the simulation to the server csma device
    TapBridgeHelper tapBridge;
    tapBridge.SetAttribute("Mode", StringValue("ConfigureLocal"));
    tapBridge.SetAttribute("DeviceName", StringValue(tapName));
    tapBridge.Install(exitnode, exitnode->GetDevice(0));

    /* Radio side (between end device and gateway) */
    LorawanHelper helper;
    NetDeviceContainer gwNetDev;
    {
        // Physiscal layer settings
        LoraPhyHelper phyHelper;
        phyHelper.SetInterference("IsolationMatrix", EnumValue(LoraInterferenceHelper::GOURSAUD));
        phyHelper.SetChannel(channel);

        // Create a LoraDeviceAddressGenerator
        /////////////////// Enables full parallelism between ELoRa instances
        uint8_t nwkId = RngSeedManager::GetRun();
        auto addrGen = CreateObject<LoraDeviceAddressGenerator>(nwkId);

        // Mac layer settings
        LorawanMacHelper macHelper;
        macHelper.SetRegion(LorawanMacHelper::EU);
        macHelper.SetAddressGenerator(addrGen);

        // Create the LoraNetDevice of the gateway
        phyHelper.SetType("ns3::GatewayLoraPhy");
        macHelper.SetType("ns3::GatewayLorawanMac");
        gwNetDev = helper.Install(phyHelper, macHelper, gateway);

        // Create the LoraNetDevice of the end device
        phyHelper.SetType("ns3::EndDeviceLoraPhy");
        macHelper.SetType("ns3::ClassAEndDeviceLorawanMac");
        helper.Install(phyHelper, macHelper, endDevice);

        // Create the jammer's PHY layer and remove it from channel receivers
        auto jamPhy = CreateObject<EndDeviceLoraPhy>();
        jamPhy->SetChannel(channel);
        channel->Remove(jamPhy);
        jamPhy->SetMobility(jammer->GetObject<MobilityModel>());
        jammer->AggregateObject(jamPhy);
    }

    /*************************
     *  Create Applications  *
     *************************/

    {
        // Install UDP forwarder in gateway
        UdpForwarderHelper forwarderHelper;
        forwarderHelper.SetAttribute("RemoteAddress", AddressValue(Ipv4Address("10.1.2.1")));
        forwarderHelper.SetAttribute("RemotePort", UintegerValue(destPort));
        forwarderHelper.Install(gateway);

        // Install application in ED
        PeriodicSenderHelper appHelper;
        appHelper.SetPeriodGenerator(
            CreateObjectWithAttributes<ConstantRandomVariable>("Constant", DoubleValue(30.0)));
        appHelper.SetPacketSizeGenerator(
            CreateObjectWithAttributes<ConstantRandomVariable>("Constant", DoubleValue(13.0)));
        appHelper.Install(endDevice);

        // Create and install jammer app
        auto jamApp = CreateObject<LoraJammer>();
        jamApp->SetAttribute("PacketSize", UintegerValue(255));
        jamApp->SetAttribute("SpreadingFactor", UintegerValue(7));
        jamApp->SetAttribute("TxPowerDBm", IntegerValue(14));
        jamApp->SetAttribute("Frequency", UintegerValue(868100000));
        jamApp->SetPhy(jammer->GetObject<EndDeviceLoraPhy>());
        jamApp->SetNode(jammer);
        jammer->AddApplication(jamApp);
    }

    /***************************
     *  Simulation and metrics *
     ***************************/

    ///////////////////// Signal handling
    OnInterrupt([](int signal) {
        csHelper.CloseConnection(signal);
        OnInterrupt(SIG_DFL); // avoid multiple executions
        exit(0);
    });
    ///////////////////// Register tenant, gateway, and device on the real server
    csHelper.SetTenant(tenant);
    csHelper.InitConnection(apiAddr, apiPort, token);
    csHelper.Register(NodeContainer(endDevice, gateway));

    // Initialize SF emulating the ADR algorithm, then add variance to path loss
    std::vector<int> devPerSF(1, 1);
    if (initializeSF)
    {
        devPerSF = LorawanMacHelper::SetSpreadingFactorsUp(endDevice, gateway, channel);
    }
    loss->SetNext(rayleigh);

    // Print current configuration
    PrintConfigSetup(1, 1, 1, devPerSF);
    helper.EnableSimulationTimePrinting(Seconds(3600));

    Config::ConnectWithoutContext(
        "/NodeList/*/DeviceList/0/$ns3::LoraNetDevice/Phy/$ns3::EndDeviceLoraPhy/EndDeviceState",
        MakeCallback(&OnStateChange));

    if (file)
    {
        helper.EnablePcap("lora", gwNetDev);
    }

    Simulator::Stop(Hours(1) * periods);

    // Start simulation
    Simulator::Run();
    Simulator::Destroy();

    return 0;
}
