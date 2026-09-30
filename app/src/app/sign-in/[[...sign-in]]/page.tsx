import { SignIn } from "@clerk/nextjs";
import { Wordmark } from "@/components/dash-nav";

export default function SignInPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8">
      <Wordmark />
      {/* Land on the dashboard after a successful sign-in (otherwise Clerk
          returns to "/", which shows Sign in again — an apparent loop). */}
      <SignIn forceRedirectUrl="/dashboard" />
    </main>
  );
}
