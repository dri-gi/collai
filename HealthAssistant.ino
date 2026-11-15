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

unsigned long startTime = 0;

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

  Serial.println("HEALTH ASSISTANT");
  Serial.println("Initializing MAX30102...");

  if (!sensor.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println("ERROR: MAX30102 not found!");
    while (1) {
      delay(1000);
    }
  }

  sensor.setup(0x1F, 4, 2, 100, 411, 4096);

  startTime = millis();

  Serial.println("elapsed_s,ir_value,bpm,average_bpm");
  Serial.println("Sensor ready. Place finger on sensor.");
}

void loop() {
  long irValue = sensor.getIR();

  // No finger: reset and print nothing.
  if (irValue <= FINGER_THRESHOLD) {
    if (fingerPresent) {
      resetReadings();
      fingerPresent = false;
    }

    delay(10);
    return;
  }

  // Newly detected finger.
  if (!fingerPresent) {
    resetReadings();
    fingerPresent = true;
  }

  // Wait until a heartbeat is detected.
  if (!checkForBeat(irValue)) {
    delay(10);
    return;
  }

  unsigned long currentTime = millis();

  // First beat establishes timing reference.
  if (lastBeat == 0) {
    lastBeat = currentTime;
    delay(10);
    return;
  }

  long delta = currentTime - lastBeat;
  float newBPM = 60000.0 / delta;

  // Reject invalid BPM values.
  if (newBPM < 40 || newBPM > 200) {
    lastBeat = currentTime;
    delay(10);
    return;
  }

  lastBeat = currentTime;
  bpm = newBPM;

  // Store valid BPM.
  rates[rateSpot] = (byte)newBPM;
  rateSpot = (rateSpot + 1) % RATE_SIZE;

  if (rateCount < RATE_SIZE) {
    rateCount++;
  }

  // Calculate average BPM.
  int total = 0;

  for (byte i = 0; i < rateCount; i++) {
    total += rates[i];
  }

  averageBPM = total / rateCount;

  // Only output positive, valid BPM readings.
  if (bpm > 0 && averageBPM > 0) {
    float elapsedSeconds =
      (currentTime - startTime) / 1000.0;

    Serial.print(elapsedSeconds, 2);
    Serial.print(",");
    Serial.print(irValue);
    Serial.print(",");
    Serial.print(bpm, 1);
    Serial.print(",");
    Serial.println(averageBPM);
  }

  delay(10);
}
