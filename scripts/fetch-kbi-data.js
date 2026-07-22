// KBI 데이터 자동 갱신 스크립트
const fs = require("fs");
const path = require("path");

const SERVICE_KEY = process.env.EKAPE_SERVICE_KEY;
if (!SERVICE_KEY) {
  console.error("EKAPE_SERVICE_KEY 환경변수가 없습니다.");
  process.exit(1);
}

const BASE_URL = "http://data.ekape.or.kr/openapi-data/service/user/grade/consumerPriceDaily";

const REGION_NAMES = [
  "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
  "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"
];

const SPECIES = [
  { key: "beef", label: "소고기", judgeKind: "4301", itemCd: "21" },
  { key: "pork", label: "돼지고기", judgeKind: "4304", itemCd: "27" },
  { key: "chicken", label: "닭고기", judgeKind: "9901", itemCd: "99" },
];

function todayYmd() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}${m}${day}`;
}

function extractTag(xml, tagName) {
  const match = xml.match(new RegExp(`<${tagName}>([^<]*)</${tagName}>`));
  return match ? match[1].trim() : null;
}

async function fetchSpecies(species) {
  const url = `${BASE_URL}?serviceKey=${SERVICE_KEY}&standYmd=${todayYmd()}&judgeKind=${species.judgeKind}&itemCd=${species.itemCd}`;

  const res = await fetch(url);
  const xml = await res.text();

  const resultCode = extractTag(xml, "resultCode");
  if (resultCode !== "00") {
    const msg = extractTag(xml, "resultMsg") || "알 수 없는 오류";
    throw new Error(`${species.label} 조회 실패 (resultCode=${resultCode}): ${msg} / 원본응답: ${xml.slice(0, 300)}`);
  }

  const regionPrices = {};
  REGION_NAMES.forEach((name, idx) => {
    const tag = `regionPrc${idx + 1}`;
    const val = extractTag(xml, tag);
    regionPrices[name] = val !== null ? Number(val) : null;
  });

  const validPrices = Object.values(regionPrices).filter((v) => v !== null && !Number.isNaN(v));
  const computedAvg = validPrices.length
    ? Math.round(validPrices.reduce((a, b) => a + b, 0) / validPrices.length)
    : null;

  return {
    label: species.label,
    unit: extractTag(xml, "unit"),
    nationalAvg: computedAvg,
    maxPrice: Number(extractTag(xml, "maxPrc")),
    minPrice: Number(extractTag(xml, "minPrc")),
    regionPrices,
  };
}

async function main() {
  const result = {
    updatedAt: new Date().toISOString(),
    source: "축산물품질평가원 축산유통정보(다봄) - 일자별 축산물소비자가격 정보",
    species: {},
    errors: {},
  };

  for (const species of SPECIES) {
    try {
      result.species[species.key] = await fetchSpecies(species);
      console.log(`[OK] ${species.label} 갱신 완료`);
    } catch (err) {
      console.error(`[FAIL] ${species.label}: ${err.message}`);
      result.errors[species.key] = err.message;
    }
  }

  const outDir = path.join(__dirname, "..", "data");
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(
    path.join(outDir, "kbi-prices.json"),
    JSON.stringify(result, null, 2),
    "utf-8"
  );

  console.log("data/kbi-prices.json 저장 완료");
}

main();
