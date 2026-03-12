import Link from "next/link";
import { ArrowRight, BarChart3, Zap, Shield, TrendingUp } from "lucide-react";

export default function Home() {
  return (
    <main className="min-h-screen bg-[#0a0a0f] text-white relative overflow-hidden">
      {/* Background effects */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-[-20%] left-1/2 -translate-x-1/2 w-[800px] h-[600px] bg-blue-500/[0.07] rounded-full blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[500px] h-[500px] bg-violet-500/[0.05] rounded-full blur-[100px]" />
        <div className="absolute top-0 inset-x-0 h-px bg-gradient-to-r from-transparent via-blue-500/20 to-transparent" />
      </div>

      {/* Nav */}
      <nav className="relative z-10 flex items-center justify-between max-w-6xl mx-auto px-6 py-5">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center">
            <BarChart3 className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-lg tracking-tight">Meta Ads AI</span>
        </div>
        <Link
          href="/auth/login"
          className="text-sm text-gray-400 hover:text-white transition-colors"
        >
          Sign in
        </Link>
      </nav>

      {/* Hero */}
      <section className="relative z-10 max-w-4xl mx-auto px-6 pt-24 pb-20 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full glass text-xs text-gray-400 mb-8 animate-fade-in">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          AI-powered campaign optimization
        </div>

        <h1 className="text-5xl sm:text-6xl lg:text-7xl font-bold leading-[1.1] tracking-tight mb-6 animate-slide-up">
          Smarter Meta Ads,{" "}
          <span className="gradient-text">powered by AI</span>
        </h1>

        <p className="text-lg sm:text-xl text-gray-400 max-w-2xl mx-auto mb-10 leading-relaxed animate-slide-up">
          Connect your Facebook & Instagram ad accounts. Let AI analyze performance,
          optimize campaigns, and grow your ROAS — all on autopilot.
        </p>

        <div className="flex flex-col sm:flex-row gap-3 justify-center animate-slide-up">
          <Link
            href="/auth/signup"
            className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 rounded-xl font-semibold text-sm transition-all glow-blue hover:scale-[1.02] active:scale-[0.98]"
          >
            Get Started Free
            <ArrowRight className="w-4 h-4" />
          </Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center justify-center gap-2 px-7 py-3.5 glass hover:bg-white/[0.06] rounded-xl font-semibold text-sm text-gray-300 transition-all"
          >
            View Dashboard
          </Link>
        </div>
      </section>

      {/* Feature grid */}
      <section className="relative z-10 max-w-5xl mx-auto px-6 pb-24">
        <div className="grid sm:grid-cols-3 gap-4">
          {[
            {
              icon: <Zap className="w-5 h-5" />,
              title: "Auto-Optimize",
              desc: "AI monitors spend, CPA, and ROAS 24/7 — pausing losers and scaling winners.",
              color: "from-amber-500/20 to-orange-500/10",
              iconBg: "bg-amber-500/10 text-amber-400",
            },
            {
              icon: <TrendingUp className="w-5 h-5" />,
              title: "Performance Insights",
              desc: "Real-time dashboards with actionable insights across all your ad accounts.",
              color: "from-blue-500/20 to-cyan-500/10",
              iconBg: "bg-blue-500/10 text-blue-400",
            },
            {
              icon: <Shield className="w-5 h-5" />,
              title: "Secure by Default",
              desc: "OAuth 2.0 with minimal permissions. Your data never leaves your control.",
              color: "from-emerald-500/20 to-teal-500/10",
              iconBg: "bg-emerald-500/10 text-emerald-400",
            },
          ].map((f) => (
            <div
              key={f.title}
              className="group glass rounded-2xl p-6 hover:bg-white/[0.04] transition-all duration-300"
            >
              <div className={`w-10 h-10 rounded-xl ${f.iconBg} flex items-center justify-center mb-4`}>
                {f.icon}
              </div>
              <h3 className="font-semibold text-white mb-2">{f.title}</h3>
              <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
