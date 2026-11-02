// SPDX-License-Identifier: AGPL-3.0-only

#include <Arduino.h>
#include <M5Unified.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_system.h>
#include <cstring>
#include <cstdio>

#include "wifi_secrets.h"

// PAN-CAMERA display: 320x240
// Header  : y=0..19
// JPEG    : y=20..199 (320x180)
// Status  : y=200..223
// Buttons : y=224..239

constexpr uint16_t UDP_PORT = 5005;
constexpr size_t VIDEO_HEADER = 20;
constexpr size_t CHUNK = 1024;
constexpr size_t MAX_CHUNKS = 32;
constexpr size_t MAX_JPEG = CHUNK * MAX_CHUNKS;

constexpr uint16_t BG = 0x0862;
constexpr uint16_t LINE = 0x21A6;

WiFiUDP udp;

static uint8_t packet[VIDEO_HEADER + CHUNK];
static uint8_t jpeg[MAX_JPEG];
static bool received[MAX_CHUNKS];

IPAddress piIP;
uint16_t piPort = 0;
bool havePeer = false;

uint32_t serverSession = 0;
uint32_t clientSession = 0;
bool haveSession = false;

uint32_t videoFrame = 0;
bool haveFrame = false;
bool assembling = false;

uint32_t jpegSize = 0;
uint16_t expectedParts = 0;
uint16_t receivedParts = 0;

uint32_t lastChunkMs = 0;
uint32_t lastVideoMs = 0;
uint32_t rxFrames = 0;
uint32_t drops = 0;
bool imageBlanked = true;

// Telemetry
bool haveTelemetry = false;
uint32_t telemetryFrame = 0;
uint32_t lastTelemetryMs = 0;
uint16_t pwmUs = 0;
int16_t errorPx = 0;
uint16_t fps10 = 0;
uint8_t trackState = 0;       // 0 standby, 1 track, 2 lost
uint8_t targetClass = 255;    // No selected class
uint8_t confidence = 0;
uint8_t objectCount = 0;
uint16_t selectedID = 65535;
bool recording = false;
uint32_t recordingSeconds = 0;

// Reliable command state
uint32_t nextSequence = 0;
uint32_t pendingSequence = 0;
char pendingCommand[12] = "";
bool pending = false;
uint8_t attempts = 0;
uint32_t lastCommandMs = 0;
uint32_t lastHeartbeatMs = 0;

// App lifecycle control remains available while the video application is stopped.
IPAddress launcherIP;
uint16_t launcherPort = 5007;
uint32_t launcherSession = 0, launcherLastMs = 0;
bool haveLauncher = false, appMenu = false, bLongPress = false;
uint8_t appState = 0;
bool launchPending = false;
uint32_t launchSequence = 0, launchLastMs = 0;
uint8_t launchAttempts = 0;
char launchAction[8] = "";

char notice[16] = "";
uint32_t noticeUntilMs = 0;

uint16_t read16(const uint8_t* p) {
    return (uint16_t(p[0]) << 8) | p[1];
}

uint32_t read32(const uint8_t* p) {
    return (uint32_t(p[0]) << 24) |
           (uint32_t(p[1]) << 16) |
           (uint32_t(p[2]) << 8) |
           uint32_t(p[3]);
}

void showNotice(const char* message) {
    snprintf(notice, sizeof(notice), "%s", message);
    noticeUntilMs = millis() + 1500;
}

bool launcherLive() {
    return haveLauncher && millis() - launcherLastMs < 3500;
}

void sendLauncher() {
    char message[96];
    snprintf(message, sizeof(message), "P2L1,%lu,%lu,%lu,%s",
             (unsigned long)launcherSession, (unsigned long)clientSession,
             (unsigned long)launchSequence, launchAction);
    udp.beginPacket(launcherIP, launcherPort);
    udp.write((const uint8_t*)message, strlen(message));
    udp.endPacket();
    launchLastMs = millis();
    launchAttempts++;
}

void queueLauncher(const char* action) {
    if (!launcherLive()) { showNotice("NO LAUNCHER"); return; }
    if (launchPending) { showNotice("WAIT ACK"); return; }
    snprintf(launchAction, sizeof(launchAction), "%s", action);
    launchSequence = ++nextSequence;
    launchAttempts = 0;
    launchPending = true;
    sendLauncher();
}

void receiveLauncher(const uint8_t* data, int n, IPAddress origin, uint16_t port) {
    if (port != 5007 || n >= 120) return;
    char text[120];
    memcpy(text, data, n); text[n] = 0;
    unsigned long session, pid, state, client, sequence, code;
    if (sscanf(text, "P2S1,%lu,%lu,%lu", &session, &pid, &state) == 3 && state <= 3) {
        if (!haveLauncher || launcherSession != session) launchPending = false;
        launcherIP = origin; launcherPort = port; launcherSession = session;
        haveLauncher = true; launcherLastMs = millis(); appState = state;
    } else if (haveLauncher && origin == launcherIP &&
               sscanf(text, "P2R1,%lu,%lu,%lu,%lu", &session, &client, &sequence, &code) == 4 &&
               session == launcherSession && client == clientSession &&
               launchPending && sequence == launchSequence) {
        launchPending = false;
        showNotice(code == 0 ? "APP REQUEST OK" : "APP ERROR");
    }
}

void drawAppMenu() {
    if (!appMenu) return;
    M5.Display.fillRoundRect(20, 42, 280, 139, 8, BG);
    M5.Display.drawRoundRect(20, 42, 280, 139, 8, TFT_CYAN);
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_CYAN);
    M5.Display.setCursor(40, 58); M5.Display.print("PI APPLICATION");
    M5.Display.setTextColor(TFT_WHITE);
    M5.Display.setCursor(40, 81);
    const char* states[] = {"STOPPED", "RUNNING / STARTING", "STOPPING...", "EXITED WITH ERROR"};
    M5.Display.print(launcherLive() ? states[appState] : "LAUNCHER OFFLINE");
    M5.Display.setCursor(40, 104); M5.Display.print("A : START  (servo enabled)");
    M5.Display.setCursor(40, 123); M5.Display.print("C : STOP   (close REC / PWM off)");
    M5.Display.setCursor(40, 149); M5.Display.print("B : BACK");
    if (launchPending) { M5.Display.setCursor(183, 149); M5.Display.print("SENDING..."); }
}

bool videoLive() {
    return haveSession &&
           millis() - lastVideoMs < 1800;
}

const char* const CLASS_NAMES[] = {
    "PERSON",
    "BICYCLE",
    "CAR",
    "MOTORCYCLE",
    "AIRPLANE",
    "BUS",
    "TRAIN",
    "TRUCK",
    "BOAT",
    "TRAFFIC LIGHT",
    "FIRE HYDRANT",
    "STOP SIGN",
    "PARKING METER",
    "BENCH",
    "BIRD",
    "CAT",
    "DOG",
    "HORSE",
    "SHEEP",
    "COW",
    "ELEPHANT",
    "BEAR",
    "ZEBRA",
    "GIRAFFE",
    "BACKPACK",
    "UMBRELLA",
    "HANDBAG",
    "TIE",
    "SUITCASE",
    "FRISBEE",
    "SKIS",
    "SNOWBOARD",
    "SPORTS BALL",
    "KITE",
    "BASEBALL BAT",
    "BASEBALL GLOVE",
    "SKATEBOARD",
    "SURFBOARD",
    "TENNIS RACKET",
    "BOTTLE",
    "WINE GLASS",
    "CUP",
    "FORK",
    "KNIFE",
    "SPOON",
    "BOWL",
    "BANANA",
    "APPLE",
    "SANDWICH",
    "ORANGE",
    "BROCCOLI",
    "CARROT",
    "HOT DOG",
    "PIZZA",
    "DONUT",
    "CAKE",
    "CHAIR",
    "COUCH",
    "POTTED PLANT",
    "BED",
    "DINING TABLE",
    "TOILET",
    "TV",
    "LAPTOP",
    "MOUSE",
    "REMOTE",
    "KEYBOARD",
    "CELL PHONE",
    "MICROWAVE",
    "OVEN",
    "TOASTER",
    "SINK",
    "REFRIGERATOR",
    "BOOK",
    "CLOCK",
    "VASE",
    "SCISSORS",
    "TEDDY BEAR",
    "HAIR DRIER",
    "TOOTHBRUSH"
};

const char* classLabel(uint8_t id) {
    return id < sizeof(CLASS_NAMES) / sizeof(CLASS_NAMES[0]) ? CLASS_NAMES[id] : "OBJECT";
}

void drawHud() {
    bool wifiOK = WiFi.status() == WL_CONNECTED;
    bool live = wifiOK && videoLive();
    bool telemetryFresh = haveTelemetry &&
        millis() - lastTelemetryMs < 1800;

    const char* mode = "WAIT";
    uint16_t modeColor = TFT_YELLOW;

    if (!wifiOK) {
        mode = "OFFLINE";
        modeColor = TFT_RED;
    } else if (!live && launcherLive()) {
        const char* appModes[] = {"APP OFF", "STARTING", "STOPPING", "APP ERROR"};
        mode = appModes[appState];
    } else if (live && telemetryFresh) {
        if (trackState == 0) {
            mode = "STANDBY";
            modeColor = TFT_CYAN;
        } else if (trackState == 1) {
            mode = "TRACK";
            modeColor = TFT_GREEN;
        } else {
            mode = "LOST";
            modeColor = TFT_YELLOW;
        }
    }

    if (millis() < noticeUntilMs) {
        mode = notice;
        modeColor = TFT_YELLOW;
    }

    // Quiet header with a distinct state badge.
    M5.Display.fillRect(0, 0, 320, 20, BG);
    M5.Display.setTextSize(1);
    M5.Display.fillCircle(8, 10, 2, live ? TFT_CYAN : TFT_DARKGREY);
    M5.Display.setTextColor(TFT_WHITE);
    M5.Display.setCursor(17, 6);
    M5.Display.print("PAN-CAMERA");

    M5.Display.fillRoundRect(110, 3, 100, 14, 4, LINE);
    M5.Display.setTextColor(modeColor);
    int modeX = 160 - M5.Display.textWidth(mode) / 2;
    M5.Display.setCursor(modeX, 6);
    M5.Display.print(mode);

    // Right: recording state, always aligned to x=315
    char recLabel[24];
    bool recActive = live && telemetryFresh && recording;

    if (!live || !telemetryFresh) {
        snprintf(recLabel, sizeof(recLabel), "REC --");
        M5.Display.setTextColor(TFT_DARKGREY);
    } else if (recording) {
        snprintf(
            recLabel, sizeof(recLabel),
            "REC %02lu:%02lu",
            (unsigned long)(recordingSeconds / 60),
            (unsigned long)(recordingSeconds % 60)
        );
        M5.Display.setTextColor(TFT_RED);
    } else {
        snprintf(recLabel, sizeof(recLabel), "REC STBY");
        M5.Display.setTextColor(TFT_LIGHTGREY);
    }

    int recX = 315 - M5.Display.textWidth(recLabel);
    M5.Display.setCursor(recX, 6);
    M5.Display.print(recLabel);

    if (recActive) {
        M5.Display.fillCircle(
            recX - 8, 10, 3, TFT_RED
        );
    }

    M5.Display.drawFastHLine(0, 19, 320, LINE);

    // Status section: two compact lines
    M5.Display.fillRect(0, 200, 320, 24, BG);
    M5.Display.setTextSize(1);

    M5.Display.setTextColor(TFT_WHITE);
    M5.Display.setCursor(7, 202);

    if (telemetryFresh && live) {
        if (selectedID == 65535) {
            M5.Display.printf(
                "%u OBJ   FREE   CONF --   ERR --",
                objectCount
            );
        } else if (trackState == 2) {
            M5.Display.printf(
                "%u OBJ   %.10s %u   CONF --",
                objectCount, classLabel(targetClass), selectedID
            );
        } else {
            M5.Display.printf(
                "%u OBJ   %.10s %u   %u%% E%+d",
                objectCount, classLabel(targetClass), selectedID, confidence, errorPx
            );
        }
    } else {
        M5.Display.print("HOLD B: PI APPLICATION MENU");
    }

    M5.Display.setTextColor(TFT_LIGHTGREY);
    M5.Display.setCursor(7, 213);

    if (telemetryFresh && live) {
        M5.Display.printf(
            "PWM:%u FPS:%u.%u RX:%lu D:%lu",
            pwmUs,
            fps10 / 10,
            fps10 % 10,
            (unsigned long)rxFrames,
            (unsigned long)drops
        );
    } else {
        M5.Display.printf(
            "RX:%lu D:%lu",
            (unsigned long)rxFrames,
            (unsigned long)drops
        );
    }

    // Three rounded action tiles aligned with the physical buttons.
    M5.Display.fillRect(0, 224, 320, 16, BG);
    for (int x : {4, 110, 216}) {
        M5.Display.fillRoundRect(x, 225, 100, 14, 3, LINE);
    }

    M5.Display.setTextColor(TFT_WHITE);
    M5.Display.setCursor(30, 229);
    M5.Display.print("A SELECT");

    M5.Display.setTextColor(TFT_CYAN);
    M5.Display.setCursor(139, 229);
    M5.Display.print(
        trackState != 0 ? "B STOP" :
        selectedID == 65535 ? "B CENTER" : "B START"
    );

    M5.Display.setTextColor(recording ? TFT_RED : TFT_WHITE);
    M5.Display.setCursor(251, 229);
    M5.Display.print(recording ? "C STOP" : "C REC");

}

void resetSession(uint32_t sid) {
    serverSession = sid;
    haveSession = true;
    haveFrame = false;
    haveTelemetry = false;
    assembling = false;

    receivedParts = 0;
    expectedParts = 0;

    rxFrames = 0;
    drops = 0;
    selectedID = 65535;
    recording = false;
    trackState = 0;

    // Old pending button commands must not enter a new session.
    pending = false;

    M5.Display.fillRect(0, 20, 320, 180, TFT_BLACK);
    imageBlanked = true;

    Serial.printf(
        "PAN-CAMERA session: %lu\n",
        (unsigned long)sid
    );
}

void receiveVideo(
    const uint8_t* data,
    size_t length,
    IPAddress origin,
    uint16_t originPort
) {
    if (length < VIDEO_HEADER) return;

    uint32_t sid = read32(data + 4);
    uint32_t fid = read32(data + 8);
    uint16_t index = read16(data + 12);
    uint16_t count = read16(data + 14);
    uint32_t size = read32(data + 16);

    if (size == 0 || size > MAX_JPEG) return;
    if (count == 0 || count > MAX_CHUNKS) return;
    if (count != (size + CHUNK - 1) / CHUNK) return;
    if (index >= count) return;

    size_t offset = size_t(index) * CHUNK;
    size_t expected = size - offset;
    if (expected > CHUNK) expected = CHUNK;

    if (length - VIDEO_HEADER != expected) return;

    if (!haveSession || sid != serverSession) {
        resetSession(sid);
    }

    piIP = origin;
    piPort = originPort;
    havePeer = true;

    if (!haveFrame || int32_t(fid - videoFrame) > 0) {
        if (assembling) drops++;

        videoFrame = fid;
        haveFrame = true;
        assembling = true;
        jpegSize = size;
        expectedParts = count;
        receivedParts = 0;
        memset(received, 0, sizeof(received));
    } else if (fid != videoFrame || !assembling) {
        return;
    }

    if (size != jpegSize || count != expectedParts) {
        return;
    }

    lastChunkMs = millis();

    if (!received[index]) {
        memcpy(
            jpeg + offset,
            data + VIDEO_HEADER,
            expected
        );

        received[index] = true;
        receivedParts++;
    }

    if (receivedParts == expectedParts) {
        // 320x180 JPEG at y=20, scale 1:1
        M5.Display.drawJpg(jpeg, jpegSize, 0, 20);

        rxFrames++;
        lastVideoMs = millis();
        imageBlanked = false;
        assembling = false;
    }
}

void receiveTelemetry(const uint8_t* data, size_t length) {
    if (length != 29 || !haveSession) return;

    if (read32(data + 4) != serverSession) return;

    uint32_t fid = read32(data + 8);

    if (haveTelemetry &&
        int32_t(fid - telemetryFrame) < 0) {
        return;
    }

    telemetryFrame = fid;

    pwmUs = read16(data + 12);
    errorPx = int16_t(read16(data + 14));
    fps10 = read16(data + 16);

    trackState = data[18];
    targetClass = data[19];
    confidence = data[20];
    objectCount = data[21];

    selectedID = read16(data + 22);
    recording = data[24] != 0;
    recordingSeconds = read32(data + 25);

    haveTelemetry = true;
    lastTelemetryMs = millis();
}

void receiveAck(const uint8_t* data, size_t length) {
    if (length >= sizeof(packet)) return;

    char message[sizeof(packet)];
    memcpy(message, data, length);
    message[length] = '\0';

    unsigned long sid, cid, seq;
    int code;

    if (sscanf(
            message,
            "P2A1,%lu,%lu,%lu,%d",
            &sid, &cid, &seq, &code
        ) != 4) {
        return;
    }

    if (!pending ||
        sid != serverSession ||
        cid != clientSession ||
        seq != pendingSequence) {
        return;
    }

    pending = false;

    if (code == 1) showNotice("NO TARGET");
    else if (code == 2) showNotice("BUSY/LOCK");
    else if (code == 3) showNotice("ERROR");
    else if (code == 4) showNotice("STALE");
}

void sendPending() {
    if (!havePeer || !haveSession) return;

    char message[96];

    snprintf(
        message, sizeof(message),
        "P2C1,%lu,%lu,%lu,%s",
        (unsigned long)serverSession,
        (unsigned long)clientSession,
        (unsigned long)pendingSequence,
        pendingCommand
    );

    udp.beginPacket(piIP, piPort);
    udp.write(
        (const uint8_t*)message,
        strlen(message)
    );
    udp.endPacket();

    attempts++;
    lastCommandMs = millis();
}

void queueCommand(const char* command) {
    if (pending) {
        showNotice("WAIT ACK");
        return;
    }

    if (!havePeer || !haveSession) {
        showNotice("NO LINK");
        return;
    }

    pendingSequence = ++nextSequence;

    snprintf(
        pendingCommand,
        sizeof(pendingCommand),
        "%s",
        command
    );

    pending = true;
    attempts = 0;
    sendPending();
}

void sendHeartbeat() {
    if (!havePeer || !haveSession) return;

    char message[80];

    snprintf(
        message, sizeof(message),
        "P2H1,%lu,%lu",
        (unsigned long)serverSession,
        (unsigned long)clientSession
    );

    udp.beginPacket(piIP, piPort);
    udp.write(
        (const uint8_t*)message,
        strlen(message)
    );
    udp.endPacket();
}

void setup() {
    Serial.begin(115200);

    auto cfg = M5.config();
    M5.begin(cfg);

    clientSession = esp_random();

    M5.Display.setBrightness(160);
    M5.Display.fillScreen(TFT_BLACK);
    M5.Display.setTextSize(2);
    M5.Display.setTextColor(TFT_WHITE);
    M5.Display.setCursor(16, 100);
    M5.Display.print("PAN-CAMERA");

    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    uint32_t started = millis();

    while (
        WiFi.status() != WL_CONNECTED &&
        millis() - started < 20000
    ) {
        M5.update();
        delay(250);
    }

    if (WiFi.status() != WL_CONNECTED) {
        M5.Display.fillScreen(TFT_BLACK);
        M5.Display.setTextColor(TFT_RED);
        M5.Display.setCursor(16, 100);
        M5.Display.print("Wi-Fi FAILED");
        return;
    }

    if (!udp.begin(UDP_PORT)) {
        M5.Display.fillScreen(TFT_BLACK);
        M5.Display.setTextColor(TFT_RED);
        M5.Display.setCursor(16, 100);
        M5.Display.print("UDP FAILED");
        return;
    }

    M5.Display.fillScreen(TFT_BLACK);
    drawHud();

    Serial.print("PAN-CAMERA ready: ");
    Serial.println(WiFi.localIP());
}

void loop() {
    M5.update();

    if (WiFi.status() != WL_CONNECTED) {
        delay(50);
        return;
    }

    // B short press acts on release; holding B opens the app menu only.
    if (M5.BtnB.wasPressed()) bLongPress = false;
    if (M5.BtnB.pressedFor(900) && !bLongPress) {
        bLongPress = true;
        appMenu = !appMenu;
        if (!appMenu) { M5.Display.fillRect(0, 20, 320, 180, TFT_BLACK); imageBlanked = true; }
    }
    if (M5.BtnB.wasReleased() && !bLongPress) {
        if (appMenu) {
            appMenu = false;
            M5.Display.fillRect(0, 20, 320, 180, TFT_BLACK); imageBlanked = true;
        } else queueCommand("TOGGLE");
    }
    if (M5.BtnA.wasPressed()) {
        if (appMenu) queueLauncher("START"); else queueCommand("SEL");
    }
    if (M5.BtnC.wasPressed()) {
        if (appMenu) queueLauncher("STOP"); else queueCommand("REC");
    }

    // UDP receive
    int length = udp.parsePacket();

    if (length > 0) {
        IPAddress origin = udp.remoteIP();
        uint16_t originPort = udp.remotePort();

        if (length <= (int)sizeof(packet)) {
            int n = udp.read(packet, length);

            if (n >= 4) {
                if (memcmp(packet, "P2S1", 4) == 0 || memcmp(packet, "P2R1", 4) == 0) {
                    receiveLauncher(packet, n, origin, originPort);
                } else if (memcmp(packet, "P2V1", 4) == 0) {
                    receiveVideo(packet, n, origin, originPort);
                    if (appMenu) drawAppMenu();
                } else if (memcmp(packet, "P2T2", 4) == 0) {
                    receiveTelemetry(packet, n);
                } else if (memcmp(packet, "P2A1", 4) == 0) {
                    receiveAck(packet, n);
                }
            }
        } else {
            uint8_t discard[64];

            while (udp.available() > 0) {
                int n = udp.available();
                if (n > (int)sizeof(discard)) {
                    n = sizeof(discard);
                }
                udp.read(discard, n);
            }
        }
    }

    uint32_t now = millis();

    if (assembling && now - lastChunkMs > 500) {
        assembling = false;
        drops++;
    }

    // Button command retry: same sequence number.
    if (pending && now - lastCommandMs >= 300) {
        if (attempts >= 6) {
            pending = false;
            showNotice("NO ACK");
        } else {
            sendPending();
        }
    }

    if (launchPending && now - launchLastMs >= 400) {
        if (launchAttempts >= 6) { launchPending = false; showNotice("APP NO ACK"); }
        else sendLauncher();
    }

    // Keepalive for the Raspberry Pi safety watchdog.
    if (havePeer && now - lastHeartbeatMs >= 500) {
        sendHeartbeat();
        lastHeartbeatMs = now;
    }

    if (haveSession &&
        !videoLive() &&
        !imageBlanked) {
        M5.Display.fillRect(
            0, 20, 320, 180, TFT_BLACK
        );
        imageBlanked = true;
    }

    static uint32_t lastHudMs = 0;

    if (now - lastHudMs >= 250) {
        drawHud();
        lastHudMs = now;
    }

    static uint32_t lastMenuMs = 0;
    if (appMenu && now - lastMenuMs >= 100) { drawAppMenu(); lastMenuMs = now; }
    delay(1);
}
