import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/router";

import { auth, onAuthStateChanged, signOut } from "../utils/firebase";

const TARGET_SAMPLE_RATE = 16_000;
const BUFFER_SECONDS = 2;
const PROCESSOR_BUFFER_SIZE = 4_096;

function createId(prefix) {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function toMono(inputBuffer) {
  const mono = new Float32Array(inputBuffer.length);
  const channelCount = inputBuffer.numberOfChannels;

  for (let channel = 0; channel < channelCount; channel += 1) {
    const samples = inputBuffer.getChannelData(channel);
    for (let index = 0; index < samples.length; index += 1) {
      mono[index] += samples[index] / channelCount;
    }
  }
  return mono;
}

function takeSamples(frames, offsetRef, sampleCount) {
  const result = new Float32Array(sampleCount);
  let written = 0;

  while (written < sampleCount && frames.length) {
    const frame = frames[0];
    const available = frame.length - offsetRef.current;
    const needed = sampleCount - written;
    const amount = Math.min(available, needed);

    result.set(
      frame.subarray(offsetRef.current, offsetRef.current + amount),
      written,
    );
    written += amount;
    offsetRef.current += amount;

    if (offsetRef.current === frame.length) {
      frames.shift();
      offsetRef.current = 0;
    }
  }
  return result;
}

function resampleTo16k(samples, sourceRate) {
  if (sourceRate === TARGET_SAMPLE_RATE) return samples;

  const outputLength = Math.round(
    (samples.length * TARGET_SAMPLE_RATE) / sourceRate,
  );
  const output = new Float32Array(outputLength);
  const ratio = sourceRate / TARGET_SAMPLE_RATE;

  for (let index = 0; index < outputLength; index += 1) {
    const sourcePosition = index * ratio;
    const before = Math.floor(sourcePosition);
    const after = Math.min(before + 1, samples.length - 1);
    const fraction = sourcePosition - before;
    output[index] = samples[before] * (1 - fraction) + samples[after] * fraction;
  }
  return output;
}

function floatToPcm16(samples) {
  const pcm = new Int16Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    pcm[index] = sample < 0 ? sample * 32_768 : sample * 32_767;
  }
  return pcm;
}

function websocketUrl(meetingId, userId) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const query = new URLSearchParams({ user_id: userId });
  return `${apiUrl.replace(/^http/, "ws").replace(/\/$/, "")}/ws/${encodeURIComponent(meetingId)}?${query}`;
}

export default function Home() {
  const router = useRouter();
  const [meetingId, setMeetingId] = useState("");
  const [currentUser, setCurrentUser] = useState(null);
  const [authReady, setAuthReady] = useState(false);
  const [isMeeting, setIsMeeting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState("Ready to start.");
  const [duration, setDuration] = useState("5");
  const [summary, setSummary] = useState(null);
  const [summaryStatus, setSummaryStatus] = useState("");

  const socketRef = useRef(null);
  const streamRef = useRef(null);
  const audioContextRef = useRef(null);
  const sourceRef = useRef(null);
  const processorRef = useRef(null);
  const pendingFramesRef = useRef([]);
  const pendingSampleCountRef = useRef(0);
  const pendingOffsetRef = useRef(0);
  const manualStopRef = useRef(false);

  useEffect(() => {
    return onAuthStateChanged(auth, async (user) => {
      if (!user) {
        window.localStorage.removeItem("firebaseIdToken");
        window.localStorage.removeItem("firebaseUid");
        setCurrentUser(null);
        setAuthReady(true);
        router.replace("/login");
        return;
      }

      try {
        const token = await user.getIdToken();
        window.localStorage.setItem("firebaseIdToken", token);
        window.localStorage.setItem("firebaseUid", user.uid);
        setCurrentUser(user);
        setAuthReady(true);
      } catch {
        router.replace("/login");
      }
    });
  }, [router]);

  const releaseMedia = useCallback((closeSocket) => {
    if (processorRef.current) {
      processorRef.current.onaudioprocess = null;
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    if (closeSocket && socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }

    pendingFramesRef.current = [];
    pendingSampleCountRef.current = 0;
    pendingOffsetRef.current = 0;
  }, []);

  const stopMeeting = useCallback(() => {
    manualStopRef.current = true;
    releaseMedia(true);
    setIsMeeting(false);
    setConnectionStatus("Meeting stopped.");
  }, [releaseMedia]);

  useEffect(() => {
    return () => {
      manualStopRef.current = true;
      releaseMedia(true);
    };
  }, [releaseMedia]);

  const startMeeting = async () => {
    if (isMeeting) return;

    const user = auth.currentUser;
    if (!user) {
      router.replace("/login");
      return;
    }

    setSummary(null);
    setSummaryStatus("");
    setConnectionStatus("Requesting microphone access…");
    manualStopRef.current = false;

    const nextMeetingId = createId("meeting");
    try {
      const token = await user.getIdToken();
      window.localStorage.setItem("firebaseIdToken", token);
      window.localStorage.setItem("firebaseUid", user.uid);
    } catch {
      setConnectionStatus("Could not refresh your Firebase session.");
      return;
    }
    const socket = new WebSocket(websocketUrl(nextMeetingId, user.uid));
    socket.binaryType = "arraybuffer";
    socketRef.current = socket;

    socket.onopen = () => setConnectionStatus("Connected. Listening for audio…");
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "audio_ack") {
          setConnectionStatus(
            `Live — ${message.buffered_duration_ms} ms buffered`,
          );
        }
      } catch {
        // Ignore non-JSON server messages.
      }
    };
    socket.onerror = () => setConnectionStatus("WebSocket connection error.");
    socket.onclose = () => {
      if (!manualStopRef.current) {
        manualStopRef.current = true;
        releaseMedia(false);
        socketRef.current = null;
        setConnectionStatus("WebSocket connection closed.");
        setIsMeeting(false);
      }
    };

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
        video: false,
      });
      if (manualStopRef.current || socket.readyState === WebSocket.CLOSED) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      const audioContext = new AudioContextClass();
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(
        PROCESSOR_BUFFER_SIZE,
        1,
        1,
      );
      const sourceSamplesPerChunk = Math.round(
        audioContext.sampleRate * BUFFER_SECONDS,
      );

      processor.onaudioprocess = (event) => {
        const monoFrame = toMono(event.inputBuffer);
        pendingFramesRef.current.push(monoFrame);
        pendingSampleCountRef.current += monoFrame.length;

        while (pendingSampleCountRef.current >= sourceSamplesPerChunk) {
          const sourceChunk = takeSamples(
            pendingFramesRef.current,
            pendingOffsetRef,
            sourceSamplesPerChunk,
          );
          pendingSampleCountRef.current -= sourceSamplesPerChunk;

          const audio16k = resampleTo16k(sourceChunk, audioContext.sampleRate);
          const pcm = floatToPcm16(audio16k);
          if (socketRef.current?.readyState === WebSocket.OPEN) {
            socketRef.current.send(pcm.buffer);
          }
        }
      };

      streamRef.current = stream;
      audioContextRef.current = audioContext;
      sourceRef.current = source;
      processorRef.current = processor;

      source.connect(processor);
      processor.connect(audioContext.destination);
      await audioContext.resume();

      setMeetingId(nextMeetingId);
      setIsMeeting(true);
    } catch (error) {
      manualStopRef.current = true;
      releaseMedia(true);
      setConnectionStatus(
        `Could not start the meeting: ${error.message || "microphone access was denied."}`,
      );
    }
  };

  const getSummary = async () => {
    if (!meetingId) {
      setSummaryStatus("Start a meeting before requesting a summary.");
      return;
    }

    setSummary(null);
    setSummaryStatus("Generating summary…");
    const headers = { "Content-Type": "application/json" };

    try {
      const user = auth.currentUser;
      if (!user) {
        router.replace("/login");
        return;
      }
      const firebaseIdToken = await user.getIdToken(true);
      window.localStorage.setItem("firebaseIdToken", firebaseIdToken);
      window.localStorage.setItem("firebaseUid", user.uid);
      headers.Authorization = `Bearer ${firebaseIdToken}`;

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${apiUrl.replace(/\/$/, "")}/api/summarize`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          meeting_id: meetingId,
          duration: Number(duration),
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "The summary request failed.");
      }

      setSummary(data);
      setSummaryStatus("Summary ready.");
    } catch (error) {
      setSummaryStatus(error.message || "The summary request failed.");
    }
  };

  const logout = async () => {
    manualStopRef.current = true;
    releaseMedia(true);
    await signOut(auth);
    window.localStorage.removeItem("firebaseIdToken");
    window.localStorage.removeItem("firebaseUid");
    router.replace("/login");
  };

  if (!authReady) {
    return <main className="container">Checking your session…</main>;
  }

  if (!currentUser) {
    return null;
  }

  return (
    <main className="container">
      <section>
        <p className="eyebrow">Live meeting summarizer</p>
        <h1>Capture the conversation. Keep the decisions.</h1>
        <p className="muted">{connectionStatus}</p>
        <p className="muted">Signed in as {currentUser.email || currentUser.uid}</p>

        <div className="controls">
          <button type="button" onClick={startMeeting} disabled={isMeeting}>
            Start Meeting
          </button>
          <button type="button" onClick={stopMeeting} disabled={!isMeeting}>
            Stop
          </button>
          <button type="button" onClick={logout}>
            Log out
          </button>
        </div>

        {meetingId && <p className="meeting-id">Meeting ID: {meetingId}</p>}
      </section>

      <section className="summary-panel">
        <h2>Meeting summary</h2>
        <div className="controls">
          <label htmlFor="duration">Last</label>
          <select
            id="duration"
            value={duration}
            onChange={(event) => setDuration(event.target.value)}
          >
            <option value="3">3 minutes</option>
            <option value="5">5 minutes</option>
            <option value="10">10 minutes</option>
          </select>
          <button type="button" onClick={getSummary}>
            Get Summary
          </button>
        </div>
        {summaryStatus && <p className="muted">{summaryStatus}</p>}

        {summary && (
          <article className="summary-result">
            <p>{summary.summary}</p>
            <h3>Key points</h3>
            <ul>
              {summary.key_points.map((point, index) => (
                <li key={`${point}-${index}`}>{point}</li>
              ))}
            </ul>
            <h3>Action items</h3>
            <ul>
              {summary.action_items.map((item, index) => (
                <li key={`${item}-${index}`}>{item}</li>
              ))}
            </ul>
          </article>
        )}
      </section>

      <style jsx>{`
        .container { max-width: 760px; margin: 0 auto; padding: 48px 24px; font-family: Arial, sans-serif; }
        .eyebrow { color: #4f46e5; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
        h1 { font-size: clamp(2rem, 6vw, 3.5rem); margin: 0.25rem 0 0.75rem; }
        h2 { margin-top: 0; }
        .muted { color: #5b6472; }
        .controls { align-items: center; display: flex; flex-wrap: wrap; gap: 12px; margin: 24px 0; }
        button, select { border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; padding: 10px 16px; }
        button { background: #4f46e5; color: white; cursor: pointer; }
        button:disabled { background: #94a3b8; cursor: not-allowed; }
        .meeting-id { color: #334155; font-family: monospace; font-size: 0.85rem; overflow-wrap: anywhere; }
        .summary-panel { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; margin-top: 40px; padding: 24px; }
        .summary-result { border-top: 1px solid #e2e8f0; margin-top: 20px; padding-top: 16px; }
        h3 { font-size: 1rem; margin-bottom: 6px; }
      `}</style>
    </main>
  );
}
