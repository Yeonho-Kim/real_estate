// 공개해도 되는 설정값만 둔다. 비밀키는 GitHub Secrets 에만 저장한다.
window.APP_CONFIG = {
  // developers.kakao.com 앱의 JavaScript 키. [앱] > [플랫폼 키] > [JavaScript 키] > [JavaScript SDK 도메인] 에 사이트 도메인 등록 필요.
  KAKAO_JS_KEY: "6db932ec1f7df1c51987823b63de2b20",
  // 웹 푸시 공개키. 짝이 되는 비밀키는 GitHub Secret VAPID_PRIVATE_KEY 에 있다. 바꿀 때는 둘을 함께 바꾼다.
  VAPID_PUBLIC_KEY: "BJMzOrncwt84MOMYhChoAwdba7iDTcbkaFHBm_6Zln-yT2uhdJBQRiwB_03lQTO4NPp9wp8waXToGI6r34VTU-8",
  // 데이터 경로 (GitHub Pages 에서는 _site/data 로 복사됨)
  DATA_BASE: "./data",
  // 지도 초기 위치 (마포·서대문·영등포·동작 사이)
  CENTER: { lat: 37.535, lng: 126.93 },
  ZOOM: 6,
};
