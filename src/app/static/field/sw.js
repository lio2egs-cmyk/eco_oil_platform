// Service worker מינימלי — קיומו מאפשר התקנת אפליקציה מלאה (WebAPK) עם אייקון אמיתי,
// במקום "קיצור דרך" עם תג כרום. לא מתערב ברשת ולא שומר מטמון.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
