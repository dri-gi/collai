#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"

MAX30105 sensor;

const long FINGER_THRESHOLD = 10000;

const byte RATE_SIZE = 8;
byte rates[RATE_SIZE];

byte rateSpot = 0;
byte rateCount = 0;

long lastBeat = 0;

float bpm = 0;
int averageBPM = 0;

unsigned long lastPrint = 0;

bool fingerPresent = false;

void resetReadings() {
  lastBeat = 0;
  bpm = 0;
  averageBPM = 0;

  rateSpot = 0;
  rateCount = 0;

  for (byte i = 0; i < RATE_SIZE; i++) {
    rates[i] = 0;
  }
}

void setup() {
  Serial.begin(9600);
  Wire.begin();

  Serial.println();
  Serial.println("==============================");
  Serial.println("       HEALTH ASSISTANT");
  Serial.println("==============================");
  Serial.println();

  Serial.println("Initializing MAX30102...");

  if (!sensor.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println("ERROR: MAX30102 not found!");
    Serial.println("Check SDA, SCL, VCC and GND.");

    while (1) {
      delay(1000);
    }
  }

  byte ledBrightness = 0x1F;
  byte sampleAverage = 4;
  byte ledMode = 2;
  int sampleRate = 100;
  int pulseWidth = 411;
  int adcRange = 4096;

  sensor.setup(
    ledBrightness,
    sampleAverage,
    ledMode,
    sampleRate,
    pulseWidth,
    adcRange
  );

  Serial.println("MAX30102 connected!");
  Serial.println("Place finger on sensor.");
  Serial.println();
}

void loop() {
  long irValue = sensor.getIR();

  if (irValue > FINGER_THRESHOLD) {
    if (!fingerPresent) {
      Serial.println();
      Serial.println("Finger detected!");

      resetReadings();

      fingerPresent = true;
    }

    if (checkForBeat(irValue)) {
      long currentTime = millis();

      if (lastBeat != 0) {
        long delta = currentTime - lastBeat;

        float newBPM = 60000.0 / delta;

        if (newBPM > 40 && newBPM < 200) {
          bpm = newBPM;

          rates[rateSpot] = (byte)newBPM;

          rateSpot++;

          if (rateSpot >= RATE_SIZE) {
            rateSpot = 0;
          }

          if (rateCount < RATE_SIZE) {
            rateCount++;
          }

          int total = 0;

          for (byte i = 0; i < rateCount; i++) {
            total += rates[i];
          }

          averageBPM = total / rateCount;
        }
      }

      lastBeat = currentTime;
    }
  } else {
    if (fingerPresent) {
      Serial.println();
      Serial.println("Finger removed.");

      resetReadings();

      fingerPresent = false;
    }
  }

  if (millis() - lastPrint >= 1000) {
    Serial.print("IR: ");
    Serial.print(irValue);

    Serial.print(" | ");

    if (!fingerPresent) {
      Serial.println("No finger detected.");
    } else if (lastBeat == 0 || millis() - lastBeat > 2500) {
      Serial.println("Waiting for heartbeat...");
    } else {
      Serial.print("BPM: ");
      Serial.print(bpm, 1);

      Serial.print(" | Average BPM: ");
      Serial.println(averageBPM);
    }

    lastPrint = millis();
  }

  delay(10);
}
