/*
 * Set of utilities to keep top example files more clean.
 */

#include "elora-example-utilities.h"

#include <regex>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("EloraUtilities");

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
double
ComputeArea(double range, int rings)
{
    if (rings == 1)
    {
        return pow(range / 1000, 2) * M_PI;
    }

    double radius = range * std::cos(M_PI / 6);
    int ngateways = 3 * rings * rings - 3 * rings + 1;

    double hexag = range / 1000 * radius / 1000 * 3;
    double disc = pow(range / 1000, 2) * M_PI;
    return (ngateways - 6 * (rings - 1)) * hexag   // Internal hexagons
           + 3 * (hexag + disc)                    // Vertices
           + 2 * (rings - 2) * (2 * hexag + disc); // Sides
}

/**
 * Print initial configuration
 */
void
PrintConfigSetup(int nDevs, double range, int rings, std::vector<int>& devPerSF)
{
    double area = ComputeArea(range, rings);
    std::stringstream ss;
    // ss << std::setprecision (10);
    ss << "Area: " << area << " km^2, Density: " << nDevs / area << " devs/km^2\n";
    ss << "\n|- SF distribution:    ";
    for (int j = (int)devPerSF.size() - 1; j >= 0; --j)
    {
        ss << "SF" << 12 - j << ":" << devPerSF[j] << ", ";
    }
    ss << "\n";
    ss << "\nAll configurations terminated. Starting simulation...\n\n"
       << "--------------------------------------------------------------------------------\n";
    std::cout << ss.str();
}

/**
 * Setup action on interrupt
 */
void
OnInterrupt(sighandler_t action)
{
    for (int s : signals)
    {
        std::signal(s, action);
    }
}

std::vector<LorawanHelper::TraceLevel>
ParseTraceLevels(std::string s)
{
    std::regex rx("PKT|DEV|SF|GW|NET|\\{((PKT|DEV|SF|GW|NET),)*(PKT|DEV|SF|GW|NET)\\}");
    NS_ASSERT_MSG(std::regex_match(s, rx),
                  "Trace granularity vector "
                      << s
                      << " ill formatted. "
                         "Syntax (no spaces): --file=OPTION or --file={OPTION,...}");

    s.erase(std::remove(s.begin(), s.end(), '{'), s.end());
    s.erase(std::remove(s.begin(), s.end(), '}'), s.end());

    std::vector<LorawanHelper::TraceLevel> out;

    std::stringstream ss(s);
    while (ss.good())
    {
        std::string substr;
        getline(ss, substr, ',');
        out.push_back(traceLevelMap.at(substr));
    }

    return out;
}

void
OnStateChange(EndDeviceLoraPhy::State oldS, EndDeviceLoraPhy::State newS)
{
    NS_LOG_DEBUG("State change " << stateMap.at(oldS) << " -> " << stateMap.at(newS));
}

} // namespace ns3
