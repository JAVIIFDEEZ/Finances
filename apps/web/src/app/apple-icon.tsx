import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

/** Home-screen icon for iOS, which does not take SVG: the same compass as `icon.svg`. */
export default function AppleIcon() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", background: "#2a78d6" }}>
        <svg width="132" height="132" viewBox="0 0 64 64">
          <circle cx="32" cy="32" r="17" fill="none" stroke="#fff" strokeWidth="4" />
          <path d="M39.5 24.5 35 35l-10.5 4.5L29 29z" fill="#fff" />
        </svg>
      </div>
    ),
    size,
  );
}
