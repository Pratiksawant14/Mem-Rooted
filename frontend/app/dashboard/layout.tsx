import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Mem-Rooted — Dashboard",
  description: "Memory network dashboard",
};

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="h-screen w-screen overflow-hidden bg-bg text-text-primary relative">
      {children}

      {/* Floating back-to-chat button */}
      <Link
        href="/"
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2.5
                   rounded-xl bg-surface border border-border text-text-secondary text-sm font-medium
                   hover:bg-surface-elevated hover:text-primary hover:border-primary/40
                   shadow-lg shadow-black/30 transition-all group"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          className="group-hover:-translate-x-0.5 transition-transform"
        >
          <path d="M19 12H5M12 19l-7-7 7-7" />
        </svg>
        Chat
      </Link>
    </div>
  );
}
