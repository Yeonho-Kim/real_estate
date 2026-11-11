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
  // 쓸 수 있는 값: {query} 동 이름 + 단지명, {name} 단지명, {addr} 도로명 주소, {sgg} 구, {umd} 동, {lat} 위도, {lng} 경도,
  //               {kakao_id} 카카오맵 장소 번호 (수집기가 자동으로 찾음. 못 찾은 단지는 값이 없음)
  // url 을 배열로 주면 앞에서부터, 필요한 값이 모두 있는 첫 주소를 쓴다.
  LINKS: [
    { label: "네이버 지도", url: "https://map.naver.com/p/search/{query}" },
    { label: "카카오맵", url: ["https://place.map.kakao.com/{kakao_id}", "https://map.kakao.com/link/map/{name},{lat},{lng}"] },
    { label: "네이버 부동산", url: "https://m.land.naver.com/search/result/{query}" },
    { label: "호갱노노", url: "https://hogangnono.com/search?q={query}" },
    { label: "KB부동산", url: "https://kbland.kr/map?xy={lat},{lng},17" },
  ],
  // 단지별 직접 주소. 네이버 지도와 호갱노노는 장소 번호를 알려 주는 공개 API 가 없어 검색 결과로 열린다.
  // 자주 보는 단지는 앱에서 "공유"로 복사한 주소를 여기에 적으면 그 단지는 바로 열린다.
  // 형식: "단지코드": { "링크 이름": "주소" }   단지코드는 data/complexes.json 의 kapt_code (주소창의 # 뒤에도 나온다)
  DIRECT_LINKS: {
    // 마포쌍용황금
    "A12105001": {
      "네이버 지도": "https://naver.me/x8karlq4",
      "호갱노노": "https://hogangnono.com/apt/NH2f/0/0",
    },
  },
};
