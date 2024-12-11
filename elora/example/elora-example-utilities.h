/*
 * Set of utilities to keep top example files more clean.
 */

#include "ns3/lora-interference-helper.h"
#include "ns3/lorawan-helper.h"

#include <csignal>
#include <vector>

using namespace ns3;
using namespace lorawan;

namespace ns3
{

/**
 * \brief Computes total deployment area
 *
 * Computes total deployment area in range of gateways placed with
 * complete radial hexagonal tiling. This assumes that the maximum
 * range devices are placed from a gateway is the side of hexagons.
 *
 * \param range Maximum device range from center of a gateway [m]
 * \param rings Number of rings of hexagons (central gateway = first ring)
 *
 * \return Deployment area [km^2]
 */
double ComputeArea(double range, int rings);

/**
 * Possible interference matrices
 */
const std::unordered_map<std::string, LoraInterferenceHelper::IsolationMatrix> sirMap = {
    {"CROCE", LoraInterferenceHelper::CROCE},
    {"GOURSAUD", LoraInterferenceHelper::GOURSAUD},
    {"ALOHA", LoraInterferenceHelper::ALOHA}};

/**
 * Print initial configuration
 */
void PrintConfigSetup(int nDevs, double range, int rings, std::vector<int>& devPerSF);

static const int signals[] = {
    SIGHUP,
    SIGINT,
    SIGQUIT,
    SIGILL,
    SIGABRT,
    SIGFPE,
    SIGSEGV,
    SIGPIPE,
    SIGTERM,
};

/**
 * Setup action on interrupt
 */
void OnInterrupt(sighandler_t action);

/**
 * Granularities of the tracing system
 */
const std::unordered_map<std::string, LorawanHelper::TraceLevel> traceLevelMap = {
    {"PKT", LorawanHelper::PKT},
    {"DEV", LorawanHelper::DEV},
    {"SF", LorawanHelper::SF},
    {"GW", LorawanHelper::GW},
    {"NET", LorawanHelper::NET}};

std::vector<LorawanHelper::TraceLevel> ParseTraceLevels(std::string s);

const std::map<EndDeviceLoraPhy::State, std::string> stateMap = {
    {EndDeviceLoraPhy::State::SLEEP, "SLEEP"},
    {EndDeviceLoraPhy::State::TX, "TX"},
    {EndDeviceLoraPhy::State::STANDBY, "STANDBY"},
    {EndDeviceLoraPhy::State::RX, "RX"}};

void OnStateChange(EndDeviceLoraPhy::State oldS, EndDeviceLoraPhy::State newS);

} // namespace ns3
