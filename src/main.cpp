#include <Arduino.h>
#include <Adafruit_PN532.h>
#include <SparkFun_GridEYE_Arduino_Library.h>
#include <Wire.h>

#define PN532_RESET_PIN (PA8) 
Adafruit_PN532 nfc(PN532_RESET_PIN, &Serial1);

GridEYE amg; 
#define NUM_PIXELS 64 

#define LED_PIN PA6
#define CMD_GET_THERMAL 0x10

void sendCardDataToPC(uint8_t *uid, uint8_t uidLength) {
    uint8_t frame_size = 6 + uidLength;
    uint8_t tx_buffer[frame_size];
    uint8_t checksum = 0;
    tx_buffer[0] = 0xA5;
    tx_buffer[1] = 0x01;
    tx_buffer[2] = uidLength;

    for(int i=0; i<3; i++) checksum ^= tx_buffer[i];

    for (int i = 0; i < uidLength; i++) {
        tx_buffer[3 + i] = uid[i];
        checksum ^= tx_buffer[3 + i];
    }
    tx_buffer[3 + uidLength] = checksum;
    tx_buffer[4 + uidLength] = 0x5A;
    Serial.write(tx_buffer, frame_size);
}

void sendThermalDataToPC() {
    uint8_t payload_len = NUM_PIXELS * 2;
    uint8_t frame_size = 6 + payload_len;
    uint8_t tx_buffer[frame_size];
    uint8_t checksum = 0;
    
    tx_buffer[0] = 0xA5;
    tx_buffer[1] = 0x11;
    tx_buffer[2] = payload_len;

    for(int i=0; i<3; i++) checksum ^= tx_buffer[i];

    for (int i = 0; i < NUM_PIXELS; i++) {
        float temp_float = amg.getPixelTemperature(i);
        int16_t temp = (int16_t)(temp_float * 100.0);
        
        uint8_t high_byte = (temp >> 8) & 0xFF;
        uint8_t low_byte = temp & 0xFF;
        
        tx_buffer[3 + i * 2] = high_byte;
        tx_buffer[4 + i * 2] = low_byte;

        checksum ^= high_byte;
        checksum ^= low_byte;
    }
    tx_buffer[3 + payload_len] = checksum;
    tx_buffer[4 + payload_len] = 0x5A;
    Serial.write(tx_buffer, frame_size);
}

void checkForPCCommands() {
    if (Serial.available() >= 5) {
        if (Serial.read() == 0xA5) {
            uint8_t command = Serial.read();
            uint8_t len = Serial.read();
            uint8_t checksum = Serial.read();
            uint8_t footer = Serial.read();

            if (footer == 0x5A) {
                uint8_t calculated_checksum = 0xA5 ^ command ^ len;
                if (checksum == calculated_checksum) {
                    if (command == CMD_GET_THERMAL && len == 0) {
                        sendThermalDataToPC();
                    }
                }
            }
        }
    }
}

void setup(void) {
    Serial.begin(115200);
    Wire.begin(); 
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH); 

    amg.begin();

    nfc.begin();
    uint32_t versiondata = nfc.getFirmwareVersion();
    if (!versiondata) {
        Serial.println("Error: PN532 board not found!");
        while (1);
    }
    nfc.SAMConfig();

    Serial.println("STM32 NFC & Thermal Reader is ready.");
}

void loop(void) {
    checkForPCCommands();

    uint8_t success;
    uint8_t uid[] = { 0, 0, 0, 0, 0, 0, 0 };
    uint8_t uidLength;
    success = nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLength, 100);

    if (success) {
        digitalWrite(LED_PIN, LOW);
        sendCardDataToPC(uid, uidLength);
        delay(1000);
    } else {
        digitalWrite(LED_PIN, HIGH);
    }
}