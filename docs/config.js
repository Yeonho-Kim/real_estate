// 공개해도 되는 설정값만 둔다. 비밀키는 GitHub Secrets 에만 저장한다.
window.APP_CONFIG = {
  // developers.kakao.com 앱의 "JavaScript 키". 플랫폼 > Web 에 사이트 도메인 등록 필요.
  KAKAO_JS_KEY: "",
  // python -m collector.gen_vapid 가 출력한 공개키
  VAPID_PUBLIC_KEY: "",
  // 데이터 경로 (GitHub Pages 에서는 _site/data 로 복사됨)
  DATA_BASE: "./data",
  // 지도 초기 위치 (마포·서대문·영등포·동작 사이)
  CENTER: { lat: 37.535, lng: 126.93 },
  ZOOM: 6,
};
