import type { MetadataRoute } from "next";

/** Lets a phone add InvestingLab to its home screen and open it full screen, like an app. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "InvestingLab",
    short_name: "InvestingLab",
    description: "Market data, portfolio analytics, Monte Carlo simulation, optimisation and savings plans.",
    start_url: "/",
    display: "standalone",
    background_color: "#0d0d0d",
    theme_color: "#0d0d0d",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/apple-icon", sizes: "180x180", type: "image/png" },
    ],
  };
}
