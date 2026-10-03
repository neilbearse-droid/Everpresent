import Link from "next/link";
import { Wordmark } from "@/components/dash-nav";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-[var(--plane)] px-6 text-center">
      <Wordmark />
      <p className="bp-display text-[56px]">Not here.</p>
      <p className="max-w-[42ch] text-[15px] text-[var(--text-2)]">
        That page doesn&apos;t exist, or it isn&apos;t yours to see. Check the link, or head back
        to your dashboard.
      </p>
      <Link href="/dashboard" className="btn btn-primary px-4 py-2">
        Back to dashboard
      </Link>
    </main>
  );
}
