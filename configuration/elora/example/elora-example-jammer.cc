/*
 * Copyright (c) 2026 University of Bologna
 *
 * SPDX-License-Identifier: GPL-2.0-only
 *
 * Author: Alessandro Aimi <alessandro.aimi@unibo.it>
 */

#include "elora-example-jammer.h"

#include "ns3/simulator.h"

namespace ns3
{
namespace lorawan
{

NS_LOG_COMPONENT_DEFINE("LoraJammer");

NS_OBJECT_ENSURE_REGISTERED(LoraJammer);

TypeId
LoraJammer::GetTypeId()
{
    static TypeId tid = TypeId("ns3::LoraJammer")
                            .SetParent<Application>()
                            .AddConstructor<LoraJammer>()
                            .SetGroupName("lorawan")
                            .AddAttribute("PacketSize",
                                          "Size of transmitted packets.",
                                          UintegerValue(18),
                                          MakeUintegerAccessor(&LoraJammer::m_pktSize),
                                          MakeUintegerChecker<uint8_t>(1))
                            .AddAttribute("SpreadingFactor",
                                          "Modulation spreading factor.",
                                          UintegerValue(7),
                                          MakeUintegerAccessor(&LoraJammer::m_sf),
                                          MakeUintegerChecker<uint8_t>(7, 12))
                            .AddAttribute("TxPowerDBm",
                                          "Transmission power (dBm).",
                                          IntegerValue(14),
                                          MakeIntegerAccessor(&LoraJammer::m_txPower),
                                          MakeIntegerChecker<int8_t>(-4, 20))
                            .AddAttribute("Frequency",
                                          "Central frequency (Hz) of the transmission channel.",
                                          UintegerValue(868100000),
                                          MakeUintegerAccessor(&LoraJammer::m_freq),
                                          MakeUintegerChecker<uint32_t>());
    return tid;
}

LoraJammer::LoraJammer()
    : m_sendEvent(EventId()),
      m_phy(nullptr)
{
}

LoraJammer::~LoraJammer()
{
    m_phy = nullptr;
}

void
LoraJammer::SetPhy(Ptr<EndDeviceLoraPhy> phy)
{
    phy->SwitchToStandby();
    m_phy = phy;
}

bool
LoraJammer::IsRunning()
{
    return m_sendEvent.IsPending();
}

void
LoraJammer::StartApplication()
{
    m_sendEvent.Cancel();
    m_sendEvent = Simulator::Schedule(MilliSeconds(8), &LoraJammer::SendPacket, this);
}

void
LoraJammer::StopApplication()
{
    m_sendEvent.Cancel();
}

void
LoraJammer::SendPacket()
{
    auto packet = Create<Packet>(m_pktSize);
    LoraPhyTxParameters params;
    params.sf = m_sf;
    params.lowDataRateOptimizationEnabled = (m_sf == 11 || m_sf == 12);
    auto toa = LoraPhy::GetTimeOnAir(packet, params);
    NS_LOG_DEBUG("TX of " << toa.As(Time::MS));
    m_phy->Send(packet, params, m_freq, m_txPower);
    m_sendEvent = Simulator::Schedule(toa + MilliSeconds(8), &LoraJammer::SendPacket, this);
}

} // namespace lorawan
} // namespace ns3
