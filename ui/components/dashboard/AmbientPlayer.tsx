"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Volume2, VolumeX } from "lucide-react";

const AUDIO_SRC =
  "https://github.com/kryptogrib/tensory/releases/download/assets-v1/Neural.Embers.mp3";
const DEFAULT_VOLUME = 0.15;
const MAX_VOLUME = 0.5;
const FADE_DURATION_MS = 6000;
const FADE_STEP_MS = 50;
const PREF_KEY = "tensory-ambient-pref";    // "on" | "off" | absent
const VOL_KEY = "tensory-ambient-volume";   // 0..1 float

/**
 * Ambient music player — loops a quiet background track.
 *
 * First visit:  auto-starts on first click anywhere, 6s fade-in to 15%.
 * Return visit: respects stored preference + saved volume level.
 * Hover to reveal vertical volume slider above the button.
 */
export function AmbientPlayer() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fadeRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);
  const [volume, setVolume] = useState(DEFAULT_VOLUME);
  const [showSlider, setShowSlider] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** Read stored volume or return default */
  const getSavedVolume = useCallback(() => {
    const saved = localStorage.getItem(VOL_KEY);
    if (saved !== null) {
      const v = parseFloat(saved);
      if (!isNaN(v) && v >= 0 && v <= MAX_VOLUME) return v;
    }
    return DEFAULT_VOLUME;
  }, []);

  /** Smoothly ramp volume from 0 → target over FADE_DURATION_MS */
  const fadeIn = useCallback((target: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.volume = 0;

    const steps = FADE_DURATION_MS / FADE_STEP_MS;
    const increment = target / steps;
    let current = 0;

    if (fadeRef.current) clearInterval(fadeRef.current);

    fadeRef.current = setInterval(() => {
      current += increment;
      if (current >= target) {
        audio.volume = target;
        if (fadeRef.current) clearInterval(fadeRef.current);
        fadeRef.current = null;
      } else {
        audio.volume = current;
      }
    }, FADE_STEP_MS);
  }, []);

  /** Smoothly ramp volume down → 0, then pause */
  const fadeOut = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const startVol = audio.volume;
    if (startVol <= 0) { audio.pause(); return; }

    const steps = FADE_DURATION_MS / FADE_STEP_MS;
    const decrement = startVol / steps;
    let current = startVol;

    if (fadeRef.current) clearInterval(fadeRef.current);

    fadeRef.current = setInterval(() => {
      current -= decrement;
      if (current <= 0.001) {
        audio.volume = 0;
        audio.pause();
        if (fadeRef.current) clearInterval(fadeRef.current);
        fadeRef.current = null;
      } else {
        audio.volume = current;
      }
    }, FADE_STEP_MS);
  }, []);

  /** Start playback with fade-in */
  const startPlaying = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const targetVol = getSavedVolume();
    audio.volume = 0;
    audio.play().then(() => {
      setPlaying(true);
      setVolume(targetVol);
      localStorage.setItem(PREF_KEY, "on");
      fadeIn(targetVol);
    }).catch(() => {
      // Browser blocked — silently ignore
    });
  }, [fadeIn, getSavedVolume]);

  // Initialize audio element (client-side only)
  useEffect(() => {
    const audio = new Audio(AUDIO_SRC);
    audio.loop = true;
    audio.volume = 0;
    audio.preload = "auto";
    audioRef.current = audio;
    setReady(true);

    return () => {
      if (fadeRef.current) clearInterval(fadeRef.current);
      audio.pause();
      audio.src = "";
      audioRef.current = null;
    };
  }, []);

  // On mount: decide behavior based on stored preference
  useEffect(() => {
    if (!ready) return;

    const pref = localStorage.getItem(PREF_KEY);

    if (pref === "on") {
      startPlaying();
    } else if (pref === null) {
      // First visit — auto-start on first interaction anywhere
      const handleFirstInteraction = () => {
        if (localStorage.getItem(PREF_KEY) === null) {
          startPlaying();
        }
        cleanup();
      };

      const cleanup = () => {
        document.removeEventListener("click", handleFirstInteraction);
        document.removeEventListener("keydown", handleFirstInteraction);
      };

      document.addEventListener("click", handleFirstInteraction, { once: true });
      document.addEventListener("keydown", handleFirstInteraction, { once: true });

      return cleanup;
    }
  }, [ready, startPlaying]);

  const toggle = useCallback(() => {
    if (playing) {
      setPlaying(false);
      localStorage.setItem(PREF_KEY, "off");
      fadeOut();
    } else {
      startPlaying();
    }
  }, [playing, fadeOut, startPlaying]);

  /** Handle volume slider change — immediate, no fade */
  const handleVolumeChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = parseFloat(e.target.value);
    setVolume(v);
    localStorage.setItem(VOL_KEY, String(v));
    if (audioRef.current && playing) {
      // Cancel any running fade so slider feels instant
      if (fadeRef.current) { clearInterval(fadeRef.current); fadeRef.current = null; }
      audioRef.current.volume = v;
    }
  }, [playing]);

  /** Show slider on hover, hide with delay */
  const handleMouseEnter = useCallback(() => {
    if (hideTimerRef.current) { clearTimeout(hideTimerRef.current); hideTimerRef.current = null; }
    setShowSlider(true);
  }, []);

  const handleMouseLeave = useCallback(() => {
    hideTimerRef.current = setTimeout(() => setShowSlider(false), 400);
  }, []);

  return (
    <div
      className="relative flex flex-col items-center"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* Volume slider — appears above button on hover */}
      {showSlider && playing && (
        <div
          className="absolute bottom-9 flex flex-col items-center rounded-lg px-1.5 py-3"
          style={{
            background: "rgba(10, 9, 8, 0.92)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            border: "1px solid rgba(217, 119, 6, 0.1)",
          }}
        >
          <input
            type="range"
            min={0}
            max={MAX_VOLUME}
            step={0.005}
            value={volume}
            onChange={handleVolumeChange}
            aria-label="Ambient volume"
            className="ambient-slider"
            style={{
              writingMode: "vertical-lr",
              direction: "rtl",
              width: "4px",
              height: "64px",
              appearance: "none",
              background: `linear-gradient(to top, #d97706 ${(volume / MAX_VOLUME) * 100}%, rgba(74, 69, 64, 0.3) ${(volume / MAX_VOLUME) * 100}%)`,
              borderRadius: "2px",
              outline: "none",
              cursor: "pointer",
            }}
          />
          <span
            className="mt-1.5 text-[0.5rem] tabular-nums"
            style={{ color: "#8a7e72" }}
          >
            {Math.round((volume / MAX_VOLUME) * 100)}%
          </span>
        </div>
      )}

      {/* Toggle button */}
      <button
        onClick={toggle}
        aria-label={playing ? "Mute ambient music" : "Play ambient music"}
        title={playing ? "Mute ambient" : "Play ambient"}
        className="group relative flex h-7 w-7 items-center justify-center rounded transition-all"
        style={{
          border: playing
            ? "1px solid rgba(217, 119, 6, 0.2)"
            : "1px solid transparent",
          background: playing
            ? "rgba(217, 119, 6, 0.08)"
            : "transparent",
        }}
      >
        {playing ? (
          <Volume2
            size={14}
            className="transition-colors"
            style={{ color: "#d97706" }}
          />
        ) : (
          <VolumeX
            size={14}
            className="transition-colors group-hover:brightness-125"
            style={{ color: "#4a4540" }}
          />
        )}

        {playing && (
          <span
            className="pointer-events-none absolute h-7 w-7 rounded-full"
            style={{
              border: "1px solid rgba(217, 119, 6, 0.15)",
              animation: "pulse-ring 3s ease-out infinite",
            }}
          />
        )}
      </button>
    </div>
  );
}
