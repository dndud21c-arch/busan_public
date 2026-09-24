import json
import re
import pandas as pd
import requests
import streamlit as st

# ==========================================
# 1. 기본 설정 및 인증키
# ==========================================
SERVICE_KEY = "cd8ddb19a12f37c0cb2aa95a1e297c8eba46ceedb6a9ff9bf7c9549572314635"
MYHOME_NOTICE_URL = "https://apis.data.go.kr/1613000/HWSPR02/rsdtRcritNtcList"
LH_LEASE_URL = "https://apis.data.go.kr/B552555/lhLeaseInfo1/lhLeaseInfo1"

# 페이지 레이아웃 설정
st.set_page_config(
    page_title="부산 청년·신혼·행복주택 원클릭 조회기",
    page_icon="🏠",
    layout="wide",
)


# ==========================================
# 2. 공고 목록 수집 함수 (마이홈 API)
# ==========================================
@st.cache_data(ttl=1800)
def fetch_busan_housing_notices(service_key=SERVICE_KEY, districts=None):
  """부산시 청년·신혼·행복주택 공고 목록 수집"""
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

    # 날짜 정리 (YYYYMMDD -> YYYY-MM-DD)
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
    st.error(f"공고 목록 수집 중 오류: {e}")
    return pd.DataFrame()


# ==========================================
# 3. LH 단지 상세 정보 조회 (LH 공식 API)
# ==========================================
@st.cache_data(ttl=1800)
def fetch_lh_complex_details(
    complex_name: str,
    region_code: str = "26",
    supply_type_code: str = "10",
    service_key: str = SERVICE_KEY,
):
  """LH 임대주택단지조회 API를 통해 평형별 세대수 및 임대료/보증금 실시간 추출"""
  params = {
      "serviceKey": service_key,
      "PG_SZ": "50",
      "PAGE": "1",
      "CNP_CD": region_code,
      "SPL_TP_CD": supply_type_code,
  }
  try:
    resp = requests.get(LH_LEASE_URL, params=params, timeout=10)
    if resp.status_code != 200:
      return pd.DataFrame()

    data = resp.json()
    items = []
    if isinstance(data, list):
      for entry in data:
        if isinstance(entry, dict) and "dsList" in entry:
          items = entry["dsList"]
          break
    elif isinstance(data, dict):
      items = data.get("dsList", [])

    if not items:
      return pd.DataFrame()

    df = pd.DataFrame(items)

    # 검색어 정제 (예: '[신규공급] 부산문현2 1블록(...)' -> '문현')
    clean_title = re.sub(
        r"\[.*?\]|\(.*?\)|부산|1블록|2블록|행복주택|최초|입주자|모집",
        "",
        complex_name,
    ).strip()
    keywords = [w for w in clean_title.split() if len(w) >= 2]

    matched_df = pd.DataFrame()
    if "SBD_LGO_NM" in df.columns:
      for kw in keywords:
        found = df[df["SBD_LGO_NM"].str.contains(kw, na=False, case=False)]
        if not found.empty:
          matched_df = found
          break

    if matched_df.empty:
      matched_df = df  # 매칭 키워드가 없을 경우 전체 데이터 유지

    results = []
    for _, row in matched_df.iterrows():
      area_m2 = float(row.get("DDO_AR", 0))
      house_cnt = int(row.get("HSH_CNT", 0))
      deposit = int(row.get("LS_GMY", 0))
      rent = int(row.get("RFE", 0))
      pyung = round(area_m2 / 3.3058, 1)

      # 가성비 지표 (평당 월세)
      rent_per_pyung = int(rent / pyung) if pyung > 0 else 0

      # 최대 상호전환 보증금 시뮬레이션 (보증금 최대 50% 추가 납부 가정)
      max_add_deposit = int(deposit * 0.5)
      reduced_rent = int(max_add_deposit * (0.07 / 12))  # 전환이율 연 7%
      loan_interest = int(
          max_add_deposit * (0.021 / 12)
      )  # 청년 버팀목 대출 연 2.1%
      final_real_expense = max(rent - reduced_rent, 0) + loan_interest
      monthly_savings = max(rent - final_real_expense, 0)

      results.append({
          "단지명": row.get("SBD_LGO_NM", ""),
          "지역": row.get("ARA_NM", ""),
          "전용면적(㎡)": area_m2,
          "공급평형": f"{pyung}평",
          "모집호수": f"{house_cnt}세대",
          "기본 보증금(원)": deposit,
          "기본 월임대료(원)": rent,
          "평당 월세": f"{rent_per_pyung:,}원/평",
          "최대 상호전환 보증금(원)": deposit + max_add_deposit,
          "전환 후 월 실부담액(원)": final_real_expense,
          "월 절감액": f"{monthly_savings:,}원 절약",
          "입주예정월": row.get("MVIN_XPC_YM", "-"),
      })

    res_df = pd.DataFrame(results)
    if not res_df.empty:
      res_df = res_df.sort_values(by="전용면적(㎡)").reset_index(drop=True)
    return res_df

  except Exception as e:
    st.error(f"LH 단지정보 API 조회 오류: {e}")
    return pd.DataFrame()


# ==========================================
# 4. 2026년 입주자격 자동 판정기
# ==========================================
class HousingEligibilityEvaluator:
  INCOME_BENCHMARK_2026 = {
      1: 3813363,
      2: 5866270,
      3: 8168429,
      4: 8802202,
      5: 9326985,
      6: 9906263,
  }
  ASSET_BENCHMARK_2026 = {
      "대학생": {
          "total_assets": 104000000,
          "car_value": 0,
          "desc": "차량 소유 불가",
      },
      "청년": {
          "total_assets": 273000000,
          "car_value": 45420000,
          "desc": "청년 단독 자산",
      },
      "신혼부부": {
          "total_assets": 345000000,
          "car_value": 45420000,
          "desc": "세대 총자산",
      },
      "고령자": {
          "total_assets": 345000000,
          "car_value": 45420000,
          "desc": "세대 총자산",
      },
  }

  @classmethod
  def evaluate(
      cls,
      household_size: int,
      monthly_income: int,
      total_assets: int,
      car_value: int,
      target_type: str,
      is_dual_income: bool = False,
  ):
    base_inc = cls.INCOME_BENCHMARK_2026.get(
        household_size, cls.INCOME_BENCHMARK_2026
    )
    addon = (
        20
        if household_size == 1
        else (
            10
            if household_size == 2
            else (20 if target_type == "신혼부부" and is_dual_income else 0)
        )
    )

    limit_100 = int(base_inc * ((100 + addon) / 100.0))
    limit_80 = int(base_inc * ((80 + addon) / 100.0))
    asset_rule = cls.ASSET_BENCHMARK_2026.get(
        target_type, cls.ASSET_BENCHMARK_2026["청년"]
    )

    pass_inc = monthly_income <= limit_100
    pass_asset = total_assets <= asset_rule["total_assets"]
    pass_car = (
        car_value == 0
        if target_type == "대학생"
        else car_value <= asset_rule["car_value"]
    )

    return {
        "최종합격여부": pass_inc and pass_asset and pass_car,
        "소득기준100": limit_100,
        "소득충족": pass_inc,
        "자산상한": asset_rule["total_assets"],
        "자산충족": pass_asset,
        "차량상한": asset_rule["car_value"],
        "차량충족": pass_car,
    }


# ==========================================
# 5. 메인 UI 구성 (Streamlit)
# ==========================================
st.title("🏠 부산 청년·신혼·행복주택 원스톱 분석기")
st.markdown(
    "공공데이터포털 및 LH 공식 단지조회 API를 연동하여 **공고 수집, 평형별 상세"
    " 임대료, 상호전환 절감액, 입주 자격**을 실시간 분석합니다."
)

# 사이드바: 내 조건 입력
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

# 사이드바 진단 결과 요약
st.sidebar.markdown("---")
st.sidebar.subheader("📌 내 자격 진단 요약")
if eval_res["최종합격여부"]:
  st.sidebar.success("✅ 행복주택 지원 가능 자격 충족!")
else:
  st.sidebar.error("❌ 지원 자격 초과 항목이 있습니다.")
st.sidebar.write(
    f"- 소득: {'충족 ✅' if eval_res['소득충족'] else '초과 ❌'} (상한"
    f" {eval_res['소득기준100'] // 10000:,}만원)"
)
st.sidebar.write(
    f"- 자산: {'충족 ✅' if eval_res['자산충족'] else '초과 ❌'} (상한"
    f" {eval_res['자산상한'] // 10000:,}만원)"
)
st.sidebar.write(
    f"- 차량: {'충족 ✅' if eval_res['차량충족'] else '초과 ❌'} (상한"
    f" {eval_res['차량상한'] // 10000:,}만원)"
)

# 메인 화면: 공고 목록 로드
st.subheader("1. 부산시 모집 공고 선택")
df_notices = fetch_busan_housing_notices()

if df_notices.empty:
  # API 응답 지연 시 샘플 선택지 제공
  sample_titles = [
      "[신규공급] 부산문현2 1블록(문현 푸르지오 트레시엘) 행복주택 최초 입주자 모집 (ID:"
      " 2015122300020806)",
      "[예비자모집] 부산정관 A-4블록 행복주택 예비입주자 모집",
      "[신규공급] 부산기장 A-2블록 행복주택 입주자 모집",
  ]
  selected_notice = st.selectbox(
      "상세 정보를 확인할 공고를 선택하세요:", options=sample_titles
  )
else:
  notice_options = [
      f"[{row['모집유형']}] {row['공고명']} ({row['자치구']})"
      for _, row in df_notices.iterrows()
  ]
  selected_notice = st.selectbox(
      "상세 정보를 확인할 공고를 선택하세요:", options=notice_options
  )

# 조작 버튼 영역
btn_col1, btn_col2 = st.columns()
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

# 추출 버튼 클릭 시 실행되는 메인 로직
if btn_extract:
  with st.spinner("LH 임대주택단지 공식 API에서 세부 평형 데이터를 조회하는 중..."):
    df_detail = fetch_lh_complex_details(
        complex_name=selected_notice,
        region_code="26",  # 부산
        supply_type_code="10",  # 행복주택
    )

  if not df_detail.empty:
    st.success(
      f"'{df_detail.iloc[0]['단지명']}'의 총 {len(df_detail)}개 평형"
      " 데이터를 성공적으로 불러왔습니다!"
    )

    # 1. 요약 메트릭 카드
    m1, m2, m3, m4 = st.columns(4)
    min_dep = df_detail["기본 보증금(원)"].min()
    max_dep = df_detail["기본 보증금(원)"].max()
    min_rent = df_detail["기본 월임대료(원)"].min()
    max_rent = df_detail["기본 월임대료(원)"].max()

    m1.metric("보증금 범위", f"{min_dep // 10000:,}만 ~ {max_dep // 10000:,}만")
    m2.metric("기본 월세 범위", f"{min_rent:,}원 ~ {max_rent:,}원")
    m3.metric("공급 평형 수", f"{len(df_detail)}개 타입")
    m4.metric(
        "내 자격 진단",
        "신청 가능 ✅" if eval_res["최종합격여부"] else "기준 초과 ❌",
    )

    st.markdown("---")
    st.subheader("📋 세부 평형별 공급호수 및 임대조건 비교표")

    # 가독성을 위한 표 데이터 포맷팅
    view_df = df_detail.copy()
    view_df["기본 보증금"] = view_df["기본 보증금(원)"].apply(
        lambda x: f"{x:,}원"
    )
    view_df["기본 월임대료"] = view_df["기본 월임대료(원)"].apply(
        lambda x: f"{x:,}원"
    )
    view_df["최대 상호전환 보증금"] = view_df["최대 상호전환 보증금(원)"].apply(
        lambda x: f"{x:,}원"
    )
    view_df["전환 후 월 실부담액"] = view_df["전환 후 월 실부담액(원)"].apply(
        lambda x: f"{x:,}원"
    )

    st.dataframe(
        view_df[[
            "단지명",
            "공급평형",
            "전용면적(㎡)",
            "모집호수",
            "기본 보증금",
            "기본 월임대료",
            "평당 월세",
            "최대 상호전환 보증금",
            "전환 후 월 실부담액",
            "월 절감액",
            "입주예정월",
        ]],
        use_container_width=True,
    )

    # 2. 추가 유용 팁 안내 박스
    st.info(
        "💡 **상호전환 팁**: 청년 버팀목 전세대출(연 2.1% 수준)을 활용하여"
        " 보증금을 최대로 높이면, 임대사업자 전환이율(연 7%)과의 금리 차이 덕분에"
        " 매달 실부담금을 크게 낮출 수 있습니다."
    )
  else:
    st.warning(
        "선택하신 공고의 세부 단지 데이터를 찾을 수 없습니다. 공고명을 확인하거나"
        " 잠시 후 다시 시도해 주세요."
    )
