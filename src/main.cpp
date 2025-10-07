#include <Arduino.h>
#include <Adafruit_PN532.h>

#define PN532_RESET_PIN (PA8) 
Adafruit_PN532 nfc(PN532_RESET_PIN, &Serial1);

#define LED_PIN PA6

void sendCardDataToPC(uint8_t *uid, uint8_t uidLength) {
    // Kích thước bản tin: Header(1) + Command(1) + Length(1) + Payload(uidLength) + Checksum(1) + Footer(1)
    uint8_t frame_size = 6 + uidLength;
    uint8_t tx_buffer[frame_size];
    uint8_t checksum = 0;
    tx_buffer[0] = 0xA5;
    checksum ^= tx_buffer[0];

    tx_buffer[1] = 0x01;
    checksum ^= tx_buffer[1];

    tx_buffer[2] = uidLength;
    checksum ^= tx_buffer[2];

    for (int i = 0; i < uidLength; i++) {
        tx_buffer[3 + i] = uid[i];
        checksum ^= tx_buffer[3 + i];
    }

    tx_buffer[3 + uidLength] = checksum;
    tx_buffer[4 + uidLength] = 0x5A;
    Serial.write(tx_buffer, frame_size);
}

void setup(void) {
    Serial.begin(115200);

    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH); 

    nfc.begin();

    uint32_t versiondata = nfc.getFirmwareVersion();
    if (!versiondata) {
        Serial.println("Error: PN532 board not found!");
        while (1);
    }

    nfc.SAMConfig();

    Serial.println("STM32 NFC Reader is ready.");
}

void loop(void) {
    uint8_t success;
    uint8_t uid[] = { 0, 0, 0, 0, 0, 0, 0 };
    uint8_t uidLength;

    success = nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLength, 500);

    if (success) {
        digitalWrite(LED_PIN, LOW); 
        sendCardDataToPC(uid, uidLength);
        delay(1000); 
        digitalWrite(LED_PIN, HIGH);
    }
}