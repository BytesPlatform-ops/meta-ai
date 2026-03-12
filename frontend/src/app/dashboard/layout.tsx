import { createClient, isSupabaseConfigured } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import Link from "next/link";
import { AlertTriangle, BarChart3 } from "lucide-react";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  if (!isSupabaseConfigured()) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center p-6">
        <div className="max-w-lg w-full text-center animate-slide-up">
          <div className="w-14 h-14 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mx-auto mb-6">
            <AlertTriangle className="w-7 h-7 text-amber-400" />
          </div>
          <h1 className="text-2xl font-bold text-white mb-2">Supabase Not Configured</h1>
          <p className="text-gray-500 mb-6 leading-relaxed">
            Set <code className="text-amber-400 bg-amber-500/[0.08] px-1.5 py-0.5 rounded text-xs">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
            <code className="text-amber-400 bg-amber-500/[0.08] px-1.5 py-0.5 rounded text-xs">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in{" "}
            your root <code className="text-gray-300 bg-white/[0.05] px-1.5 py-0.5 rounded text-xs">.env</code> file, then restart Docker.
          </p>
          <div className="glass rounded-xl p-4 text-left text-sm font-mono text-gray-400 mb-6 space-y-1">
            <p><span className="text-gray-600"># .env (project root)</span></p>
            <p>NEXT_PUBLIC_SUPABASE_URL=<span className="text-blue-400">https://your-ref.supabase.co</span></p>
            <p>NEXT_PUBLIC_SUPABASE_ANON_KEY=<span className="text-blue-400">eyJhbGciOi...</span></p>
          </div>
          <Link href="/" className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-white transition-colors">
            <BarChart3 className="w-4 h-4" /> Back to home
          </Link>
        </div>
      </div>
    );
  }

  const supabase = createClient();

  let user = null;
  try {
    const { data } = await supabase.auth.getUser();
    user = data?.user ?? null;
  } catch {
    // Network call failed — fall back to local session decode
  }

  if (!user) {
    try {
      const { data } = await supabase.auth.getSession();
      user = data?.session?.user ?? null;
    } catch {
      // Both failed
    }
  }

  if (!user) redirect("/auth/login");

  return (
    <div className="flex min-h-screen bg-[#0a0a0f]">
      <Sidebar email={user.email ?? ""}/>
      <main className="flex-1 overflow-auto relative">
        {/* Subtle top glow */}
        <div className="absolute top-0 left-1/3 w-[500px] h-[300px] bg-blue-500/[0.03] rounded-full blur-[100px] pointer-events-none" />
        <div className="relative z-10">{children}</div>
      </main>
    </div>
  );
}
