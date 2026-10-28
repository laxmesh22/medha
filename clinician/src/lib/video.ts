// Video consults run on Jitsi Meet by default: free, works in any browser or the Jitsi app, no account for patients.
// Calls open in their own tab (embedded meet.jit.si calls are cut off after 5 minutes). For real patients point
// VITE_VIDEO_BASE_URL at a self-hosted Jitsi or Jitsi-as-a-Service deployment.

export const VIDEO_BASE = ((import.meta.env.VITE_VIDEO_BASE_URL as string | undefined) || "https://meet.jit.si").replace(/\/+$/, "");
export const VIDEO_PROVIDER = new URL(VIDEO_BASE).host;

/** Room link for one person. The display name is pre-filled; everyone still sees a camera/mic check before joining. */
export function roomUrl(room: string, displayName?: string): string {
  const params = ["config.prejoinConfig.enabled=true"];
  if (displayName) params.push(`userInfo.displayName=${encodeURIComponent(JSON.stringify(displayName))}`);
  return `${VIDEO_BASE}/${encodeURIComponent(room)}#${params.join("&")}`;
}

export const patientJoinUrl = (room: string) => `${VIDEO_BASE}/${encodeURIComponent(room)}`;
