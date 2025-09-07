#include <SoapySDR/Device.hpp>
#include <SoapySDR/Formats.hpp>
#include <SoapySDR/Logger.hpp>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

using Clock = std::chrono::steady_clock;

static std::atomic<bool> g_stop{false};
void sigint_handler(int){ g_stop.store(true); }

// Map 2.4 GHz Wi-Fi channel (1–13) to center frequency in Hz.
// f_MHz = 2412 + 5*(ch-1)
static double wifi2g_ch_to_hz(int ch){
    if (ch >= 1 && ch <= 13) return (2412.0 + 5.0 * (ch - 1)) * 1e6;
    if (ch == 14) return 2484.0 * 1e6; // JP only
    throw std::runtime_error("Unsupported 2.4 GHz channel");
}

static std::string now_utc_compact(){
    using namespace std::chrono;
    auto t = system_clock::now();
    std::time_t tt = system_clock::to_time_t(t);
    std::tm gmt{};
#if defined(_WIN32)
    gmtime_s(&gmt, &tt);
#else
    gmtime_r(&tt, &gmt);
#endif
    std::ostringstream oss;
    oss << std::put_time(&gmt, "%Y%m%dT%H%M%SZ");
    return oss.str();
}

static void write_sidecar_json(
    const std::string &pathJson,
    const std::string &radio,
    const std::string &driver,
    double centerHz,
    double rate,
    size_t nsamps,
    const std::string &fmt,
    const std::string &ts_utc)
{
    std::ofstream js(pathJson, std::ios::binary);
    js << "{\n"
       << "  \"schema\": \"soapywifi.capture.v1\",\n"
       << "  \"radio\": \"" << radio << "\",\n"
       << "  \"driver\": \"" << driver << "\",\n"
       << "  \"center_hz\": " << std::fixed << std::setprecision(3) << centerHz << ",\n"
       << "  \"sample_rate\": " << std::fixed << std::setprecision(3) << rate << ",\n"
       << "  \"samples\": " << nsamps << ",\n"
       << "  \"format\": \"" << fmt << "\",\n"
       << "  \"timestamp_utc\": \"" << ts_utc << "\"\n"
       << "}\n";
}

int main(int argc, char** argv){
    SoapySDR::registerLogHandler([](const SoapySDRLogLevel, const char* msg){ std::cerr << msg << "\n"; });

    std::signal(SIGINT, sigint_handler);
#if !defined(_WIN32)
    std::signal(SIGTERM, sigint_handler);
#endif

    // Defaults
    std::string devArgs = ""; // e.g., "driver=lime" or "driver=remote,remote:driver=lime"
    int    wifiCh       = 6;      // 2.4 GHz channel
    double sampRate     = 20e6;   // 20 MHz Wi-Fi
    double rfBw         = 25e6;   // slightly wider than 20 MHz
    double gain         = 40.0;   // device-specific scalar gain (dB-ish)
    std::string outDir  = "./captures";
    double seconds      = 10.0;   // capture duration
    std::string fmt     = SOAPY_SDR_CF32; // prefer CF32

    // Parse minimal CLI
    for (int i=1;i<argc;i++){
        std::string a = argv[i];
        auto need = [&](const char* name){ if (i+1>=argc) { std::cerr<<"Missing value for "<<name<<"\n"; std::exit(2);} return std::string(argv[++i]); };
        if (a=="--args")        devArgs = need("--args");
        else if (a=="--chan")   wifiCh  = std::stoi(need("--chan"));
        else if (a=="--rate")   sampRate= std::stod(need("--rate"));
        else if (a=="--bw")     rfBw    = std::stod(need("--bw"));
        else if (a=="--gain")   gain    = std::stod(need("--gain"));
        else if (a=="--out")    outDir  = need("--out");
        else if (a=="--secs")   seconds = std::stod(need("--secs"));
        else if (a=="--fmt")    fmt     = need("--fmt"); // SOAPY_SDR_CF32 or SOAPY_SDR_CS16
        else if (a=="--help"){
            std::cout <<
            "Usage: wifi_capture [--args key=val,...] [--chan N] [--rate S]\n"
            "                   [--bw Hz] [--gain G] [--out DIR]\n"
            "                   [--secs T] [--fmt SOAPY_SDR_CF32|SOAPY_SDR_CS16]\n"
            "Examples:\n"
            "  wifi_capture --args driver=lime --chan 6 --rate 20e6 --bw 25e6 --gain 45\n"
            "  wifi_capture --args driver=remote,remote:driver=lime,remote:ip=192.168.1.50 --chan 1\n";
            return 0;
        }
    }

    // Enumerate (optional: show matches)
    auto results = SoapySDR::Device::enumerate(devArgs);
    if (results.empty()){
        std::cerr << "No SDR devices found with args: \"" << devArgs << "\"\n";
        return 1;
    }
    std::cerr << "Found " << results.size() << " device(s). Using first.\n";

    // Make device
    auto dev = std::unique_ptr<SoapySDR::Device>(SoapySDR::Device::make(devArgs));
    if (!dev){ std::cerr<<"Device::make failed\n"; return 1; }

    // Configure RX
    const auto freq = wifi2g_ch_to_hz(wifiCh);
    dev->setSampleRate(SOAPY_SDR_RX, 0, sampRate);
    dev->setBandwidth(SOAPY_SDR_RX, 0, rfBw);
    dev->setFrequency(SOAPY_SDR_RX, 0, freq);
    // Optional DC/IQ corrections if supported by driver:
    try { dev->setDCOffsetMode(SOAPY_SDR_RX, 0, true); } catch(...) {}
    try { dev->setIQBalance(SOAPY_SDR_RX, 0, std::complex<double>(0.0,0.0)); } catch(...) {}
    // Use overall gain if the driver exposes it; otherwise split across stages
    try { dev->setGain(SOAPY_SDR_RX, 0, gain); } catch(...) {}

    // Prepare output filenames
    std::string ts = now_utc_compact();
    std::ostringstream base;
    base << outDir << "/wifi2g_ch" << wifiCh << "_" << static_cast<uint64_t>(freq) << "Hz_" << static_cast<uint64_t>(sampRate) << "sps_" << ts;

    // Create stream
    int flags = 0;
    std::vector<void*> buffs(1, nullptr);
    size_t elemSize = (fmt == SOAPY_SDR_CF32 ? sizeof(float)*2 : sizeof(int16_t)*2);
    auto mtu = dev->getStreamMTU(SOAPY_SDR_RX, 0); // usually after setup
    SoapySDR::Stream* rxStream = dev->setupStream(SOAPY_SDR_RX, fmt);
    if (!rxStream){ std::cerr<<"setupStream failed\n"; return 1; }
    dev->activateStream(rxStream, 0, 0, 0);

    // Allocate buffer
    std::vector<uint8_t> buffer;
    buffer.resize(mtu * elemSize);
    buffs[0] = buffer.data();

    // Open output
    std::string binPath  = base.str() + (fmt==SOAPY_SDR_CF32 ? ".cf32" : ".cs16");
    std::string jsonPath = base.str() + ".json";
    std::FILE* f = std::fopen(binPath.c_str(), "wb");
    if (!f){ std::cerr<<"Failed to open output: "<<binPath<<"\n"; return 1; }

    const auto t0 = Clock::now();
    size_t totalSamps = 0;

    std::cerr << "Capturing " << seconds << " s @ " << sampRate << " sps on ch " << wifiCh
              << " (" << freq/1e6 << " MHz), MTU=" << mtu << ", format=" << fmt << "\n";
    while (!g_stop.load()){
        // Stop after duration
        auto elapsed = std::chrono::duration<double>(Clock::now() - t0).count();
        if (elapsed >= seconds) break;

        int flagsRead = 0;
        long long timeNs = 0;
        int ret = dev->readStream(rxStream, buffs.data(), mtu, flagsRead, timeNs, 200000 /* us timeout */);
        if (ret == SOAPY_SDR_TIMEOUT) continue;
        if (ret == SOAPY_SDR_OVERFLOW){
            std::cerr << "[warn] OVERFLOW\n";
            continue;
        }
        if (ret < 0){
            std::cerr << "[err ] readStream ret=" << ret << "\n";
            break;
        }
        size_t wrote = std::fwrite(buffer.data(), elemSize, static_cast<size_t>(ret), f);
        if (wrote != static_cast<size_t>(ret)){
            std::cerr << "[err ] fwrite short write\n";
            break;
        }
        totalSamps += static_cast<size_t>(ret);
    }

    dev->deactivateStream(rxStream);
    dev->closeStream(rxStream);
    SoapySDR::Device::unmake(dev.release());
    std::fclose(f);

    write_sidecar_json(jsonPath,
        results.front()["label"],
        results.front()["driver"],
        freq, sampRate, totalSamps, fmt, ts);

    std::cerr << "Done. Wrote " << totalSamps << " samples to " << binPath << "\n";
    std::cerr << "Sidecar: " << jsonPath << "\n";
    return 0;
}
