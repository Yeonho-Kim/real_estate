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
  // 단지 패널에 보이는 외부 서비스 링크. 순서대로 표시된다. 주소 형식이 바뀌면 여기만 고치면 된다.
  // 쓸 수 있는 값: {query} 동 이름 + 단지명, {name} 단지명, {addr} 도로명 주소, {sgg} 구, {umd} 동, {lat} 위도, {lng} 경도
  // 호갱노노·네이버 부동산·KB부동산은 단지 고유번호를 알 수 없어 검색이나 좌표로 연다.
  LINKS: [
    { label: "네이버 지도", url: "https://map.naver.com/p/search/{query}" },
    { label: "카카오맵", url: "https://map.kakao.com/link/map/{name},{lat},{lng}" },
    { label: "네이버 부동산", url: "https://m.land.naver.com/search/result/{query}" },
    { label: "호갱노노", url: "https://hogangnono.com/search?q={query}" },
    { label: "KB부동산", url: "https://kbland.kr/map?xy={lat},{lng},17" },
  ],
};
