/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Hide the floating Next.js developer indicator ("N" button) in dev.
  devIndicators: false,
  // Traces the minimal set of files/node_modules the server actually needs
  // into .next/standalone — lets the production Dockerfile copy a small,
  // self-contained bundle instead of the entire node_modules tree.
  output: "standalone",
  // Import only the icons/charts/components actually used instead of whole packages (smaller bundles,
  // far fewer modules to compile on the first visit to a page).
  experimental: {
    optimizePackageImports: ["lucide-react", "recharts", "antd", "@ant-design/icons"],
  },
};

module.exports = nextConfig;
