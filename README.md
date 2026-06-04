# Market Data Systemization & Conditional Execution Pipeline

## 프로젝트 개요
본 프로젝트는 외부 오픈 API를 연동하여 실시간으로 시장 데이터를 수집하고, 사전에 정의된 논리적 규칙(Rule-based)에 따라 프로세스를 시스템화하는 파이썬(Python) 기반 시스템입니다. 
수작업 모니터링 업무의 비효율성을 개선하고, 데이터 기반의 정확하고 신속한 프로세스 실행을 구현하기 위해 기획되었습니다.

## 핵심 역량 및 비즈니스 임팩트
단순한 코드 작성을 넘어, 방대한 데이터를 체계적으로 관리하고 예외 상황을 통제하는 '업무 시스템화 기획력'에 초점을 맞추었습니다.

* 데이터 처리 및 구조화: 파편화된 외부 API 데이터를 수집, 정제하여 유의미한 수치 지표로 가공하는 파이프라인 구축
* 논리적 요구사항 정의: 복잡한 시장 상황을 State Machine 구조로 분류하여, 조건과 실행 로직을 명확하게 매핑
* 리스크 관리 및 예외 처리: 통신 지연, 비정상 데이터 입력, 실행 오차 등 발생 가능한 변수를 예측하고 방어 로직 설계

## 주요 기능 (Core Features)

1. Open API 기반 실시간 데이터 파싱
   * REST API를 통한 대량의 시계열 데이터 실시간 수집 및 전처리
   * 통신 제한(Rate Limit)을 고려한 안전한 데이터 호출 로직 적용

2. 복합 조건부 상태 검증 (State Machine)
   * 수집된 데이터를 바탕으로 현재의 시장 상태를 다각도로 분석하여 상태값(State) 부여
   * 단순한 단일 조건이 아닌, 복합적인 규칙 교차 검증을 통해 시스템 오작동 최소화

3. 시스템화된 트랜잭션 실행 및 모니터링
   * 검증된 조건에 완벽히 부합할 경우 즉각적인 트랜잭션(API 기반 주문 실행) 발생
   * 시스템 구동 상태 및 변동 내역을 실시간 텍스트 로그로 출력하여 추적성(Traceability) 확보

## 기술 스택 (Tech Stack)
* Language: Python 3
* Data Processing: Pandas, NumPy
* API Integration: PyUpbit (Open API)

## 시스템 구동 프로세스 (Workflow)
1. `Data Ingestion`: 외부 API 호출 및 시계열 데이터 프레임 생성
2. `Metric Calculation`: 추세, 변동성 등 다중 데이터 지표 산출
3. `State Analysis`: 산출된 지표를 바탕으로 현재 환경을 논리적으로 분류
4. `Condition Check`: 사전 정의된 실행 조건 부합 여부 2중 검증
5. `Execution`: 조건 충족 시 외부 API를 통한 트랜잭션 자동 실행 및 결과 로깅

## 구동 환경 설정
본 프로젝트는 데이터 보안을 위해 환경 변수(`.env`)를 통해 민감한 API 인증 키 값을 철저히 분리하여 관리합니다.

1. 필수 패키지 설치
```bash
pip install -r requirements.txt
