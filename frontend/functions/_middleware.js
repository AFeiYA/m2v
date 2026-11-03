export async function onRequest(context) {
  const url = new URL(context.request.url);
  const hostname = url.hostname.toLowerCase();

  // Redirect marketing pages on www.fovea.si and mv.fovea.si to fovea.si
  if (hostname === "www.fovea.si" || hostname === "mv.fovea.si") {
    const pathname = url.pathname;
    const isApp = (
      pathname === "/app" ||
      pathname.startsWith("/app/") ||
      pathname === "/lyric-editor" ||
      pathname.startsWith("/lyric-editor/") ||
      pathname === "/motion-studio" ||
      pathname.startsWith("/motion-studio/") ||
      pathname === "/motion-lab" ||
      pathname.startsWith("/motion-lab/") ||
      pathname === "/rhythm-studio" ||
      pathname.startsWith("/rhythm-studio/") ||
      pathname === "/gallery" ||
      pathname.startsWith("/gallery/") ||
      pathname === "/storyboard" ||
      pathname.startsWith("/storyboard/") ||
      pathname.startsWith("/api/") ||
      pathname.startsWith("/local/") ||
      pathname.startsWith("/static/") ||
      pathname.startsWith("/motion/") ||
      pathname.startsWith("/remotion/")
    );

    // On www.fovea.si always redirect, on mv.fovea.si redirect non-app (marketing) pages
    if (hostname === "www.fovea.si" || !isApp) {
      url.hostname = "fovea.si";
      url.protocol = "https:";
      return Response.redirect(url.toString(), 301);
    }
  }

  return await context.next();
}
