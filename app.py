import json
import re
from bs4 import BeautifulSoup
import pandas as pd
import requests
import streamlit as st

# ==============================================================================
# 1. 기본 설정 및 인증키
# ==============================================================================
SERVICE_KEY = "cd8ddb19a12f37c0cb2aa95a1e297c8eba46ceedb6a9ff9bf7c9549572314635"
MYHOME_NOTICE_URL = "https://apis.data.go.kr/1613000/HWSPR02/rsdtRcritNtcList"
LH_LEASE_URL = "https://apis.data.go.kr/B552555/lhLeaseInfo1/lhLeaseInfo1"

st.set_page_config(
    page_title="부산 청년·신혼·행복주택 종합 분석기",
    page_icon="🏠",
    layout="wide",
)


# ==============================================================================
# 2. 공고 목록 수집 함수 (마이홈 API)
# ==============================================================================
@st.cache_data(ttl=1800)
def fetch_busan_housing_notices(service_key=SERVICE_KEY, districts=None):
  """부산시 행복주택 및 청년/신혼 임대 공고 목록 수집"""
  params = {
      "serviceKey": service_key,
      "pageNo": "1",
      "numOfRows": "50",
      "brtcCode": "26",  # 부산광역시
      "suplyTyCode": "10",  # 행복주택
  }
  try:
    resp = requests.get(MYHOME_NOTICE_URL, params=params, timeout=10)
    if resp.status_code != 200:
      return pd.DataFrame()

    data = resp.json()
    items = data.get("response", {}).get("body", {}).get("item", [])
    if not items:
      return pd.DataFrame()

    df = pd.DataFrame(items)

    def classify_recruit_type(title):
      title = str(title)
      if any(k in title for k in ["예비입주자", "예비자", "예비"]):
        return "예비자모집"
      return "신규공급"

    def classify_target(row):
      title = str(row.get("pblancNm", ""))
      suply = str(row.get("suplyTyNm", ""))
      if suply == "행복주택" or "행복주택" in title:
        return "행복주택"
      elif "청년" in title and "매입임대" in suply:
        return "청년 매입임대"
      elif "신혼" in title and "매입임대" in suply:
        return "신혼부부 매입임대"
      return "기타"

    df["주택유형"] = df.apply(classify_target, axis=1)
    df["모집유형"] = df["pblancNm"].apply(classify_recruit_type)

    # 타겟 유형만 필터링
    df_filtered = df[
        df["주택유형"].isin(["행복주택", "청년 매입임대", "신혼부부 매입임대"])
    ].copy()

    # 날짜 포맷팅
    for col in ["beginDe", "endDe", "rcritPblancDe", "przwnerPresnatnDe"]:
      if col in df_filtered.columns:
        df_filtered[col] = df_filtered[col].apply(
            lambda x: (
                f"{str(x)[:4]}-{str(x)[4:6]}-{str(x)[6:]}"
                if len(str(x)) == 8
                else str(x)
            )
        )

    if districts:
      df_filtered = df_filtered[df_filtered["signguNm"].isin(districts)]

    columns_map = {
        "모집유형": "모집유형",
        "주택유형": "주택유형",
        "pblancNm": "공고명",
        "signguNm": "자치구",
        "hsmpNm": "단지명",
        "sumSuplyCo": "모집호수",
        "beginDe": "접수시작일",
        "endDe": "접수마감일",
        "url": "상세링크",
    }
    available_cols = [c for c in columns_map.keys() if c in df_filtered.columns]
    return (
        df_filtered[available_cols]
        .rename(columns=columns_map)
        .reset_index(drop=True)
    )
  except Exception as e:
    st.error(f"공고 목록 수집 오류: {e}")
    return pd.DataFrame()


# ==============================================================================
# 3. [신규 추가] LH OpenAPI(lhLeaseInfo1) - 단지 내 평형별 물리적 세대수 전용 조회
# ==============================================================================
@st.cache_data(ttl=1800)
def fetch_lh_physical_units(
    complex_name: str,
    region_code: str = "26",
    supply_type_code: str = "10",
    service_key: str = SERVICE_KEY,
) -> pd.DataFrame:
  """LH 임대주택단지조회 OpenAPI(lhLeaseInfo1)를 활용하여

  단지 내 평형별 '물리적 총 세대수(예: 39.85㎡ 48세대, 44.88㎡ 96세대)' 정보를 조회합니다.
  """
  params = {
      "serviceKey": service_key,
      "PG_SZ": "50",
      "PAGE": "1",
      "CNP_CD": region_code,
      "SPL_TP_CD": supply_type_code,
  }
  try:
    resp = requests.get(LH_LEASE_URL, params=params, timeout=8)
    if resp.status_code != 200:
      return pd.DataFrame()

    data = resp.json()
    items = []
    if isinstance(data, list):
      for elem in data:
        if isinstance(elem, dict) and "dsList" in elem:
          items = elem["dsList"]
          break
    elif isinstance(data, dict):
      items = data.get("dsList", [])

    if not items:
      return pd.DataFrame()

    df = pd.DataFrame(items)

    # 공고 단지명 키워드 매칭 (특수문자 및 불필요 수식어 제거)
    clean_kw = re.sub(
        r"\[.*?\]|\(.*?\)|부산|1블록|2블록|행복주택|최초|입주자|모집",
        "",
        complex_name,
    ).strip()
    search_terms = [w for w in clean_kw.split() if len(w) >= 2]

    matched_df = pd.DataFrame()
    if "SBD_LGO_NM" in df.columns:
      for kw in search_terms:
        found = df[df["SBD_LGO_NM"].str.contains(kw, na=False, case=False)]
        if not found.empty:
          matched_df = found
          break

    if matched_df.empty:
      matched_df = df

    records = []
    for _, row in matched_df.iterrows():
      area_m2 = float(row.get("DDO_AR", 0))
      house_cnt = int(row.get("HSH_CNT", 0))
      pyung = round(area_m2 / 3.3058, 1)

      records.append({
          "단지명": row.get("SBD_LGO_NM", ""),
          "지역": row.get("ARA_NM", ""),
          "전용면적(㎡)": area_m2,
          "공급평형": f"{pyung}평형",
          "단지 물리적 세대수": f"{house_cnt}세대",
          "최초입주예정": row.get("MVIN_XPC_YM", "-"),
      })

    res_df = pd.DataFrame(records)
    if not res_df.empty and "전용면적(㎡)" in res_df.columns:
      res_df = res_df.sort_values(by="전용면적(㎡)").reset_index(drop=True)
    return res_df

  except Exception as e:
    print(f"LH 단지조회 API 호출 예외: {e}")
    return pd.DataFrame()


# ==============================================================================
# 4. 공고문 상세 파싱 함수 (계층별 모집호수 및 임대조건 정밀 추출)
# ==============================================================================
def parse_housing_detail(detail_url: str) -> pd.DataFrame:
  """마이홈 상세 URL을 통해 계층별(청년·신혼·고령자) 전용면적과 우선/일반 모집호수를 정밀 추출합니다."""
  if not detail_url or not str(detail_url).startswith("http"):
    return pd.DataFrame()

  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/120.0.0.0 Safari/537.36"
      )
  }

  try:
    resp = requests.get(detail_url, headers=headers, timeout=8)
    if resp.status_code != 200:
      return pd.DataFrame()

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(separator="\n")
    results = []

    pattern = re.compile(
        r"([0-9]+[A-Za-z]?(?:\([^)]+\))?)\s+"
        r"전용면적\s*([0-9.]+)\s*㎡.*?"
        r"월임대료\(원\)\s*([0-9,]+).*?"
        r"계\s*([0-9]+)\s+우선공급\s*([0-9]+)\s+일반공급\s*([0-9]+).*?"
        r"계\s*([0-9,]+)",
        re.DOTALL,
    )

    for m in pattern.finditer(text):
      housing_type = m.group(1).strip()
      area_m2 = float(m.group(2))
      rent = int(m.group(3).replace(",", ""))
      total_cnt = int(m.group(4))
      prio_cnt = int(m.group(5))
      gene_cnt = int(m.group(6))
      deposit = int(m.group(7).replace(",", ""))

      target = "일반"
      for t_name in ["청년", "신혼부부", "신혼", "대학생", "고령자", "주거급여"]:
        if t_name in housing_type:
          target = "신혼부부" if t_name in ["신혼부부", "신혼"] else t_name
          break

      results.append({
          "주택형": housing_type,
          "공급대상": target,
          "전용면적(㎡)": area_m2,
          "평수": f"{round(area_m2 / 3.3058, 1)}평",
          "모집인원 합계": f"{total_cnt}세대",
          "우선공급": f"{prio_cnt}세대",
          "일반공급": f"{gene_cnt}세대",
          "기본보증금": f"{deposit:,}원" if deposit > 0 else "공고문 참조",
          "월임대료": f"{rent:,}원" if rent > 0 else "공고문 참조",
      })

    df_detail = pd.DataFrame(results)
    if not df_detail.empty and "전용면적(㎡)" in df_detail.columns:
      df_detail = df_detail.sort_values(by="전용면적(㎡)").reset_index(
          drop=True
      )
    return df_detail

  except Exception as e:
    print(f"상세 파싱 오류: {e}")
    return pd.DataFrame()


# ==============================================================================
# 5. 최대 상호전환 월세 절감 시뮬레이터 함수
# ==============================================================================
def simulate_converted_rent(
    base_deposit,
    base_rent,
    max_add_deposit,
    conversion_rate=0.07,
    loan_interest_rate=0.021,
):
  """기본 보증금/월세 기준 상호전환 시 월 예상 실부담액(월세 + 버팀목 이자) 계산"""
  reduced_rent = max_add_deposit * (conversion_rate / 12)
  final_rent = max(base_rent - reduced_rent, 0)
  monthly_loan_interest = max_add_deposit * (loan_interest_rate / 12)
  total_monthly_expense = final_rent + monthly_loan_interest
  monthly_savings = max(base_rent - total_monthly_expense, 0)

  return {
      "기본조건": f"보증금 {base_deposit // 10000:,}만 / 월 {int(base_rent):,}원",
      "최대전환조건": (
          f"보증금 {(base_deposit + max_add_deposit) // 10000:,}만 / 월"
          f" {int(final_rent):,}원"
      ),
      "예상대출이자": (
          f"월 {int(monthly_loan_interest):,}원 (연"
          f" {loan_interest_rate * 100:.1f}% 가정)"
      ),
      "월예상실부담금": (
          f"월 {int(total_monthly_expense):,}원 (월세 + 대출이자)"
      ),
      "월절감액": f"월 {int(monthly_savings):,}원 절약",
  }


# ==============================================================================
# 6. 2026년 기준 입주 자격 자동 판정기
# ==============================================================================
class HousingEligibilityEvaluator:
  INCOME_BENCHMARK_2026 = {
      1: 3813363,
      2: 5866270,
      3: 8168429,
      4: 8802202,
      5: 9326985,
      6: 9906263,
  }
  PER_ADDITIONAL_PERSON = 579278
  ASSET_BENCHMARK_2026 = {
      "대학생": {
          "total_assets": 104000000,
          "car_value": 0,
          "desc": "자동차 소유 불가",
      },
      "청년": {
          "total_assets": 273000000,
          "car_value": 45420000,
          "desc": "청년 단독 자산 기준",
      },
      "신혼부부": {
          "total_assets": 345000000,
          "car_value": 45420000,
          "desc": "세대 총자산 기준",
      },
      "고령자": {
          "total_assets": 345000000,
          "car_value": 45420000,
          "desc": "세대 총자산 기준",
      },
  }

  @classmethod
  def get_base_income(cls, household_size: int) -> int:
    if household_size in cls.INCOME_BENCHMARK_2026:
      return cls.INCOME_BENCHMARK_2026[household_size]
    elif household_size > 6:
      return cls.INCOME_BENCHMARK_2026[6] + (
          household_size - 6
      ) * cls.PER_ADDITIONAL_PERSON
    return cls.INCOME_BENCHMARK_2026

  @classmethod
  def calculate_income_limits(
      cls,
      household_size: int,
      is_dual_income: bool = False,
      target_type: str = "청년",
  ):
    base = cls.get_base_income(household_size)
    addon_p = 0
    if household_size == 1:
      addon_p = 20
    elif household_size == 2:
      addon_p = 10
    if target_type == "신혼부부" and is_dual_income:
      addon_p += 20
    ratio_100 = 100 + addon_p
    ratio_80 = 80 + addon_p
    return {
        "limit_100": int(base * (ratio_100 / 100.0)),
        "limit_80": int(base * (ratio_80 / 100.0)),
    }

  @classmethod
  def evaluate(
      cls,
      household_size: int,
      monthly_income: int,
      total_assets: int,
      car_value: int = 0,
      target_type: str = "청년",
      is_dual_income: bool = False,
  ):
    inc_limits = cls.calculate_income_limits(
        household_size, is_dual_income, target_type
    )
    asset_rules = cls.ASSET_BENCHMARK_2026.get(
        target_type, cls.ASSET_BENCHMARK_2026["청년"]
    )
    pass_inc_100 = monthly_income <= inc_limits["limit_100"]
    pass_asset = total_assets <= asset_rules["total_assets"]
    pass_car = (
        (car_value == 0)
        if target_type == "대학생"
        else (car_value <= asset_rules["car_value"])
    )
    return {
        "최종합격": pass_inc_100 and pass_asset and pass_car,
        "소득기준": inc_limits["limit_100"],
        "소득통과": pass_inc_100,
        "자산기준": asset_rules["total_assets"],
        "자산통과": pass_asset,
        "차량기준": asset_rules["car_value"],
        "차량통과": pass_car,
    }


# ==============================================================================
# 7. 메인 Streamlit 대시보드 UI
# ==============================================================================
st.title("🏠 부산 청년·신혼·행복주택 종합 분석기")
st.caption(
    "마이홈 공고 실시간 파싱 & LH 임대주택단지 OpenAPI(lhLeaseInfo1) 물리적 세대수"
    " 통합 조회 시스템"
)

# [사이드바] 조건 설정 및 자격 판정
st.sidebar.header("🔍 나의 입주 자격 진단 조건")
user_target = st.sidebar.selectbox(
    "신청 계층", ["청년", "신혼부부", "대학생", "고령자"]
)
user_family = st.sidebar.number_input("가구원 수", min_value=1, max_value=6, value=1)
user_income = (
    st.sidebar.number_input(
        "월평균 세전 소득 (만원)", min_value=0, value=300, step=10
    )
    * 10000
)
user_assets = (
    st.sidebar.number_input(
        "총 자산가액 (만원)", min_value=0, value=10000, step=500
    )
    * 10000
)
user_car = (
    st.sidebar.number_input(
        "차량 기준가액 (만원)", min_value=0, value=1500, step=100
    )
    * 10000
)
is_dual = (
    st.sidebar.checkbox("맞벌이 여부 (신혼부부 전용)")
    if user_target == "신혼부부"
    else False
)

eval_res = HousingEligibilityEvaluator.evaluate(
    household_size=user_family,
    monthly_income=user_income,
    total_assets=user_assets,
    car_value=user_car,
    target_type=user_target,
    is_dual_income=is_dual,
)

st.sidebar.markdown("---")
st.sidebar.subheader("📌 내 자격 진단 요약")
if eval_res["최종합격"]:
  st.sidebar.success("✅ 행복주택 지원 가능 자격 충족!")
else:
  st.sidebar.error("❌ 지원 자격 초과 항목이 있습니다.")
st.sidebar.write(
    f"- 소득: {'충족 ✅' if eval_res['소득통과'] else '초과 ❌'} (상한"
    f" {eval_res['소득기준'] // 10000:,}만원)"
)
st.sidebar.write(
    f"- 자산: {'충족 ✅' if eval_res['자산통과'] else '초과 ❌'} (상한"
    f" {eval_res['자산기준'] // 10000:,}만원)"
)
st.sidebar.write(
    f"- 차량: {'충족 ✅' if eval_res['차량통과'] else '초과 ❌'} (상한"
    f" {eval_res['차량기준'] // 10000:,}만원)"
)

# [본문 1] 공고 목록 로드 및 선택
st.subheader("1. 공고 선택")
df_notices = fetch_busan_housing_notices()

if df_notices.empty:
  notice_options = [
      "[신규공급] 부산문현2 1블록(문현 푸르지오 트레시엘) 행복주택 최초 입주자 모집 (남구)"
  ]
  selected_notice = st.selectbox(
      "상세 정보를 확인할 공고를 선택하세요:", options=notice_options
  )
  selected_url = "https://m.myhome.go.kr/hws/portal/sch/selectRsdtRcritNtcDetailView.do?pblancId=21323&houseSn=1"
else:
  notice_options = [
      f"[{row['모집유형']}] {row['공고명']} ({row['자치구']})"
      for _, row in df_notices.iterrows()
  ]
  selected_notice = st.selectbox(
      "상세 정보를 확인할 공고를 선택하세요:", options=notice_options
  )
  # 선택된 공고의 URL 매칭
  sel_idx = notice_options.index(selected_notice)
  selected_url = df_notices.iloc[sel_idx].get("상세링크", "")

st.markdown("---")

# [본문 2] LH OpenAPI 연동: 단지 내 평형별 물리적 세대수 전용 카드
st.subheader("2. 🏢 [LH 공식 단지정보] 평형별 물리적 총 세대수")
st.caption(
    "※ lhLeaseInfo1 OpenAPI를 통해 단지 설계 마스터 기준의 평형별 물리적 총"
    " 세대수를 확인합니다."
)

df_lh_units = fetch_lh_physical_units(complex_name=selected_notice)

if not df_lh_units.empty:
  # 요약 메트릭 표시 (4개 컬럼)
  col_m1, col_m2, col_m3 = st.columns(3)
  col_m1.metric("확인 단지명", df_lh_units.iloc[0]["단지명"])
  col_m2.metric("공급 평형 수", f"{len(df_lh_units)}개 평형 타입")
  col_m3.metric(
      "단지 전체 세대수 합계",
      f"{sum([int(s.replace('세대', '')) for s in df_lh_units['단지 물리적 세대수']]):,}세대",
  )

  # 물리적 세대수 테이블 출력
  st.dataframe(
      df_lh_units[[
          "단지명",
          "공급평형",
          "전용면적(㎡)",
          "단지 물리적 세대수",
          "지역",
          "최초입주예정",
      ]],
      use_container_width=True,
  )
else:
  st.info("해당 공고의 LH 단지 마스터 세대수 정보를 불러오는 중입니다...")

st.markdown("---")

# [본문 3] 계층별 세부 배정표 실시간 추출 (마이홈 공고문 파싱)
st.subheader("3. 📋 [공고 상세 배정표] 계층별 공급 평형 및 우선/일반 모집호수")

btn_col1, btn_col2 = st.columns(2)
with btn_col1:
  btn_extract = st.button(
      "📊 공고 세부 평형 및 우선/일반 배정표 실시간 추출",
      type="primary",
      use_container_width=True,
  )
with btn_col2:
  st.link_button(
      "🌐 LH 청약플러스 공식 웹페이지 이동",
      "https://apply.lh.or.kr",
      use_container_width=True,
  )

if btn_extract:
  with st.spinner("공고문에서 계층별(청년/신혼/고령자) 세부 배정표를 파싱 중입니다..."):
    df_detail = parse_housing_detail(selected_url)

  if not df_detail.empty:
    st.success(
        f"총 {len(df_detail)}건의 계층별/평형별 세부 배정 내역을 추출했습니다!"
    )
    st.dataframe(df_detail, use_container_width=True)
  else:
    st.warning(
        "공고 상세 웹페이지 응답 지연으로 계층별 배정표를 자동으로 긁어오지 못했습니다.\n\n"
        "위 **'2. LH 공식 단지정보'**의 평형별 물리적 세대수(예: 39.85㎡ 48세대, 44.88㎡ 96세대)를 참고하시고, "
        "정확한 계층별 배정 비율은 **'🌐 LH 청약플러스 공식 웹페이지 이동'** 버튼을 통해 공고문 첨부파일을 확인해 주세요."
    )

st.markdown("---")

# [본문 4] 상호전환 보증금 계산기
st.subheader("4. 💰 최대 상호전환 보증금 및 실부담금 시뮬레이터")
st.caption(
    "보증금을 최대로 높이고 청년 버팀목 대출(연 2.1%)을 결합했을 때 월 절감액을"
    " 계산합니다."
)

calc_col1, calc_col2, calc_col3 = st.columns(3)
with calc_col1:
  input_base_dep = (
      st.number_input(
          "기본 임대보증금 (만원)", min_value=0, value=6000, step=500
      )
      * 10000
  )
with calc_col2:
  input_base_rent = st.number_input(
      "기본 월임대료 (원)", min_value=0, value=250000, step=10000
  )
with calc_col3:
  input_add_dep = (
      st.number_input(
          "추가 납부 보증금 (만원)", min_value=0, value=3000, step=500
      )
      * 10000
  )

sim_res = simulate_converted_rent(
    input_base_dep, input_base_rent, input_add_dep
)
s1, s2, s3 = st.columns(3)
s1.metric("전환 후 최종 월 실부담액", sim_res["월예상실부담금"])
s2.metric("매달 아끼는 금액", sim_res["월절감액"])
s3.metric("예상 버팀목 대출이자", sim_res["예상대출이자"])
