/* 웹 푸시 구독 생성과 구독 JSON 표시 (서버 없이 GitHub Secret 에 붙여 넣는 방식). */
(function () {
  const cfg = window.APP_CONFIG || {};

  function urlBase64ToUint8Array(base64) {
    const padding = "=".repeat((4 - (base64.length % 4)) % 4);
    const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  async function registerSW() {
    if (!("serviceWorker" in navigator)) throw new Error("이 브라우저는 서비스 워커를 지원하지 않습니다.");
    const reg = await navigator.serviceWorker.register("./sw.js");
    await navigator.serviceWorker.ready;
    return reg;
  }

  async function subscribe() {
    if (!cfg.VAPID_PUBLIC_KEY) throw new Error("docs/config.js 의 VAPID_PUBLIC_KEY 가 비어 있습니다.");
    if (!("PushManager" in window)) throw new Error("이 브라우저는 웹 푸시를 지원하지 않습니다. (iOS 는 홈 화면에 추가한 뒤 가능)");
    const reg = await registerSW();
    const permission = await Notification.requestPermission();
    if (permission !== "granted") throw new Error("알림 권한이 거부되었습니다.");
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(cfg.VAPID_PUBLIC_KEY),
      });
    }
    return sub;
  }

  async function showTest() {
    const reg = await registerSW();
    await reg.showNotification("아파트 실거래 지도", { body: "테스트 알림입니다. 이 알림이 보이면 브라우저 설정은 정상입니다.", icon: "./icon.svg" });
  }

  window.PushSetup = { subscribe, showTest };
})();
