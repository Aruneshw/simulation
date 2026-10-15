// minimal host stub for syntax checking generated firmware
#pragma once
#include <cmath>
#include <cstdlib>
#include <cstdint>
#include <cstdio>
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define CHANGE 3
#define TWO_PI 6.283185307179586
#define IRAM_ATTR
#define ESP_ARDUINO_VERSION_MAJOR 3
using std::fabs;
template<class T> T constrain(T x, T a, T b){ return x<a?a:(x>b?b:x); }
inline int digitalRead(int){return 0;} inline void digitalWrite(int,int){} inline void pinMode(int,int){}
inline void analogWrite(int,int){} inline void ledcAttach(int,int,int){} inline void ledcWrite(int,int){}
inline int digitalPinToInterrupt(int p){return p;} inline void attachInterrupt(int, void(*)(), int){}
inline unsigned long millis(){return 0;} inline unsigned long micros(){return 0;}
inline void noInterrupts(){} inline void interrupts(){}
struct SerialT { void begin(long){} int available(){return 0;} int read(){return 0;}
  template<class T> void print(T){} template<class T> void print(T,int){} template<class T> void println(T,int){} };
static SerialT Serial;
