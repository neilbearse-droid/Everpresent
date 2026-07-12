import Link from "next/link";

export default function LandingPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-start justify-center gap-6 px-8">
      <h1 className="text-4xl font-semibold tracking-tight">EverPresent</h1>
      <p className="text-lg text-slate-300">
        See how visible your brand is inside AI-generated answers — across surfaces, across
        personas, next to your competitors.
      </p>
      <p className="text-sm text-slate-400">
        EverPresent is invite-only. If your organization has access, sign in below.
      </p>
      <Link
        href="/sign-in"
        className="rounded-md bg-indigo-500 px-5 py-2.5 font-medium text-white hover:bg-indigo-400"
      >
        Sign in
      </Link>
    </main>
  );
}
