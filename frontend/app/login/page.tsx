"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim()) return;

    setLoading(true);
    try {
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const { data } = await axios.post(`${API_BASE}/api/auth/login`, {
        username: username.trim(),
      });
      
      localStorage.setItem("mem_user_id", data.user_id);
      localStorage.setItem("mem_username", data.username);
      
      router.push("/");
    } catch (error) {
      console.error("Login failed:", error);
      alert("Failed to login. Check console for details.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0A0A0B] flex flex-col items-center justify-center text-zinc-100 p-4 font-sans selection:bg-indigo-500/30">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[20%] left-[50%] -translate-x-1/2 w-[800px] h-[800px] bg-indigo-500/10 rounded-full blur-[120px] opacity-50 mix-blend-screen" />
        <div className="absolute top-[40%] left-[50%] -translate-x-1/2 w-[600px] h-[600px] bg-fuchsia-500/10 rounded-full blur-[100px] opacity-40 mix-blend-screen" />
      </div>

      <div className="relative z-10 w-full max-w-md">
        <div className="text-center mb-10">
          <h1 className="text-4xl font-light tracking-tight mb-3">
            Mem<span className="text-indigo-400 font-medium">Rooted</span>
          </h1>
          <p className="text-zinc-400 text-sm">
            Enter a username to access your isolated memory graph.
          </p>
        </div>

        <form onSubmit={handleLogin} className="bg-[#121214]/80 backdrop-blur-xl border border-zinc-800/50 p-8 rounded-2xl shadow-2xl shadow-black/50">
          <div className="mb-6">
            <label className="block text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g., Alex or Pratik"
              className="w-full bg-[#0A0A0B] border border-zinc-800 rounded-lg px-4 py-3 text-zinc-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-colors placeholder:text-zinc-600"
              autoFocus
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading || !username.trim()}
            className="w-full bg-indigo-500 hover:bg-indigo-600 disabled:bg-zinc-800 disabled:text-zinc-500 text-white font-medium py-3 rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            {loading ? (
              <div className="w-5 h-5 border-2 border-zinc-400 border-t-white rounded-full animate-spin" />
            ) : (
              "Access Memory Graph"
            )}
          </button>
        </form>
        
        <p className="text-center text-xs text-zinc-600 mt-8">
          A new profile is automatically created if the username does not exist.
        </p>
      </div>
    </div>
  );
}
