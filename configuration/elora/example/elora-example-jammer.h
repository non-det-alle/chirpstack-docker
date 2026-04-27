/*
 * Copyright (c) 2026 University of Bologna
 *
 * SPDX-License-Identifier: GPL-2.0-only
 *
 * Author: Alessandro Aimi <alessandro.aimi@unibo.it>
 */

#ifndef LORA_JAMMER_H
#define LORA_JAMMER_H

#include "ns3/application.h"
#include "ns3/end-device-lora-phy.h"

namespace ns3
{
namespace lorawan
{

class LoraJammer : public Application
{
  public:
    /**
     *  Register this type.
     *  @return The object TypeId.
     */
    static TypeId GetTypeId();

    LoraJammer();           //!< Default constructor
    ~LoraJammer() override; //!< Destructor

    /**
     * Set the PHY layer.
     */
    void SetPhy(Ptr<EndDeviceLoraPhy> phy);

    /**
     * True if the application is currently running
     */
    bool IsRunning();

  protected:
    /**
     * Start the application by scheduling the first SendPacket event
     */
    void StartApplication() override;

    /**
     * Stop the application
     */
    void StopApplication() override;

    /**
     * Send a packet using the PHY layer Send method
     */
    virtual void SendPacket();

    EventId m_sendEvent; //!< The sending event scheduled as next

    uint8_t m_pktSize; //!< The packet size
    uint8_t m_sf;      //!< The spreading factor
    int8_t m_txPower;  //!< The transmission power in dBm
    uint32_t m_freq;   //!< The channel frequency in Hz

    Ptr<EndDeviceLoraPhy> m_phy; //!< The PHY layer of this node
};

} // namespace lorawan
} // namespace ns3

#endif /* LORA_JAMMER_H */
