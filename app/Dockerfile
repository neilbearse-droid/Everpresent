FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
# The app renders dynamically and reads CLERK_PUBLISHABLE_KEY at runtime
# (see src/app/layout.tsx), so no real secret is baked into the image. This
# placeholder only satisfies the build's prerender pass; it is never used at
# runtime. Managed hosts (Render) need no build args.
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_Y2xlY2suZXhhbXBsZS5jb20k
ENV NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
