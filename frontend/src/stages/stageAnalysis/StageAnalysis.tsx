// ⑤ 결과분석(phase3.md §19, D3-62; 라우트 …/stage/analysis[?source=batch|doe&id=…], 프런트 전용 — 내부 5 = ⑥ 최적화).
// 입력 = 결과 표 1종(analysis/resultTable): 출처 (a) 일괄 예측 배치(④) · (b) 해석 DOE(①). 머리: 출처 세그먼트·드롭다운·비교 추가·메타 칩.
// 본문: 1줄 = 결과 표 | 결과 컨투어(3D, 선택 행) 1:1, 2줄 = 그래프 탭(변수–응답·설계공간 지도·영향도·커브(출처 a만), 12칸). 선택 모델 selected = run 번호(표·그래프·지도·커브 공유).
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type PredictBatchSummary, type TrainDoe } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { Card } from "../../components/ui";
import { ReportButton } from "../../components/ReportButton";
import { reportApi, type AnalysisReportQuery } from "../../api/reports";
import { commonResponses, META_DIFF_TEXT, metaChips, metaDiffers, mismatchText, nameSetDiff, NO_COMMON_RESP_TEXT } from "../../analysis/compare";
import { isOkState, type ResultTable } from "../../analysis/resultTable";
import { EquivTab } from "../../analysis/equiv/EquivTab";
import { AnalysisTable, sortRtRows } from "./AnalysisTable";
import { AnalysisContourCard } from "./AnalysisContourCard";
import { AnalysisTabs } from "./AnalysisTabs";
import { CompareSlot } from "./CompareSlot";
import { EMPTY_TEXT, readSource, SourcePicker, writeSource, type SourceSel } from "./SourcePicker";
import { useResultTable } from "./useResultTable";

export function StageAnalysis() {
  const { study } = useStudy();
  const [sp, setSp] = useSearchParams();
  const [batches, setBatches] = useState<PredictBatchSummary[] | null>(null);
  const [does, setDoes] = useState<TrainDoe[] | null>(null);
  const [base, setBase] = useState<SourceSel | null>(null);
  const [cmp, setCmp] = useState<SourceSel | null>(null);

  useEffect(() => {
    let alive = true;
    api.batches(study.id).then((x) => alive && setBatches(x)).catch(() => alive && setBatches([]));
    api.trainDoes(study.id).then((x) => alive && setDoes(x)).catch(() => alive && setDoes([]));
    return () => {
      alive = false;
    };
  }, [study.id]);

  // 첫 출처 정하기: 쿼리 > 저장값(목록에 있는 것) > 완료 배치 첫 번째 > 준비된 DOE 첫 번째
  useEffect(() => {
    if (base || !batches || !does) return;
    const qs = sp.get("source");
    const qid = sp.get("id");
    const doneBatches = batches.filter((b) => b.status === "DONE");
    const readyDoes = does.filter((d) => d.status === "READY");
    let pick: SourceSel | null = null;
    if ((qs === "batch" || qs === "doe") && qid) pick = { kind: qs, id: qid };
    else {
      const saved = readSource();
      if (saved?.kind === "batch" && doneBatches.some((b) => b.id === saved.id)) pick = saved;
      else if (saved?.kind === "doe" && readyDoes.some((d) => d.id === saved.id)) pick = saved;
      else if (saved && !saved.id) pick = saved.kind === "batch" && doneBatches[0] ? { kind: "batch", id: doneBatches[0].id } : saved.kind === "doe" && readyDoes[0] ? { kind: "doe", id: readyDoes[0].id } : null;
      if (!pick) pick = doneBatches[0] ? { kind: "batch", id: doneBatches[0].id } : readyDoes[0] ? { kind: "doe", id: readyDoes[0].id } : null;
    }
    setBase(pick);
  }, [batches, does, base]);

  // 같은 화면에서 쿼리만 바뀌어도(④ 링크 카드 등) 출처를 따라간다
  const qs = sp.get("source");
  const qid = sp.get("id");
  useEffect(() => {
    if ((qs === "batch" || qs === "doe") && qid && (base?.kind !== qs || base?.id !== qid)) setBase({ kind: qs, id: qid });
  }, [qs, qid]);

  const doeKey = (id: string | null) => {
    const d = does?.find((x) => x.id === id);
    return d ? `${d.sample_status}|${d.status}` : "";
  };
  const baseLoaded = useResultTable(base?.kind ?? null, base?.id || null, doeKey(base?.id ?? null));
  const cmpLoaded = useResultTable(cmp?.kind ?? null, cmp?.id || null, doeKey(cmp?.id ?? null));

  const pickBase = (s: SourceSel) => {
    setBase(s);
    writeSource(s);
    if (s.id) setSp({ source: s.kind, id: s.id }, { replace: true });
  };
  const addCompare = () => {
    const kind = base?.kind === "doe" ? "batch" : "doe";
    const list = kind === "batch" ? (batches ?? []).filter((b) => b.status === "DONE").map((b) => b.id) : (does ?? []).filter((d) => d.status === "READY").map((d) => d.id);
    setCmp({ kind, id: list.find((i) => i !== base?.id) ?? "" });
  };

  const table = baseLoaded.table;
  const cmpTable = cmpLoaded.table;
  const diff = table && cmpTable ? nameSetDiff(table, cmpTable) : null;
  const commonResp = table && cmpTable ? commonResponses(table, cmpTable) : [];
  const message = diff && !diff.same ? mismatchText(diff) : table && cmpTable && !commonResp.length ? NO_COMMON_RESP_TEXT : null;
  const other = table && cmpTable && diff?.same && commonResp.length ? cmpTable : null;
  const metaDiff = table && cmpTable ? metaDiffers(table.meta, cmpTable.meta) : false;
  // equiv-check.md §7: ?tab=equiv → 등가성 판정 탭(기본 출처 = A, 비교 출처 = B). 기존 탭은 ?tab 없음
  const equiv = sp.get("tab") === "equiv";
  const setTab = (t: "table" | "equiv") => {
    const next = new URLSearchParams(sp);
    if (t === "equiv") next.set("tab", "equiv");
    else {
      next.delete("tab");
      next.delete("eq");
    }
    setSp(next, { replace: true });
  };
  const tabs = (
    <div className="tabs graph-tabs" role="tablist" aria-label="결과분석 탭">
      <button type="button" role="tab" aria-selected={!equiv} onClick={() => setTab("table")}>
        결과 표·그래프
      </button>
      <button type="button" role="tab" aria-selected={equiv} onClick={() => setTab("equiv")}>
        등가성 판정
      </button>
    </div>
  );

  if (!batches || !does) return <Card span={9} title="결과분석"><p className="muted small">불러오는 중…</p></Card>;
  if (equiv) {
    return (
      <>
        <Card span={9} title="결과분석" className="analysis-head" aside={tabs}>
          <p className="muted small">⑤ 등가성 판정 — 두 결과 집합(A 기준·B 비교)을 쌍으로 맞춰 지표별 허용오차(레시피)로 판정하고 이력을 남깁니다.</p>
        </Card>
        <Card span={9} title="등가성 판정" className="analysis-equiv">
          <EquivTab initialA={base && base.id ? { kind: base.kind, id: base.id } : null} initialB={cmp && cmp.id ? { kind: cmp.kind, id: cmp.id } : null} initialEq={sp.get("eq")} />
        </Card>
      </>
    );
  }
  return (
    <>
      <Card span={9} title="결과분석" className="analysis-head" aside={tabs}>
        <div className="head-row">
          <SourcePicker slot="기본" sel={base ?? { kind: "batch", id: "" }} batches={batches} does={does} onChange={pickBase} />
        </div>
        {table && <MetaChips table={table} />}
        {cmpTable && metaDiff && (
          <p className="muted small" data-testid="meta-diff">
            {META_DIFF_TEXT}
          </p>
        )}
        <CompareSlot sel={cmp} batches={batches} does={does} onChange={setCmp} onRemove={() => setCmp(null)} onAdd={addCompare} canAdd={!!table} message={message} loading={cmpLoaded.loading} error={cmpLoaded.error} />
        {cmpTable && !message && (
          <div className="head-row small">
            <span className="muted">비교 출처 메타</span>
            <MetaChips table={cmpTable} />
          </div>
        )}
      </Card>
      {!base || !base.id ? (
        <Card span={9} title="결과 표"><p className="muted analysis-empty" data-testid="analysis-empty">{EMPTY_TEXT}</p></Card>
      ) : baseLoaded.error ? (
        <Card span={9} title="결과 표"><p className="error-text" role="alert">{baseLoaded.error}</p></Card>
      ) : !table ? (
        <Card span={9} title="결과 표"><p className="muted small">불러오는 중…</p></Card>
      ) : (
        <AnalysisBody key={`${table.origin.kind}:${table.origin.id}`} table={table} other={other} studyBase={`/p/${study.project_id}/s/${study.id}`} />
      )}
    </>
  );
}

function MetaChips({ table }: { table: ResultTable }) {
  return (
    <ul className="meta-chips small" aria-label={`${table.origin.label} 메타`} data-testid="meta-chips">
      <li>{table.origin.label}</li>
      {metaChips(table.meta).map((c) => (
        <li key={c.key}>
          {c.label} {c.value}
        </li>
      ))}
    </ul>
  );
}

const srcOf = (t: ResultTable): "batch" | "doe" => (t.origin.kind === "predict_batch" ? "batch" : "doe");

function AnalysisBody({ table, other, studyBase }: { table: ResultTable; other: ResultTable | null; studyBase: string }) {
  const { study } = useStudy();
  const respNames = table.responses.map((r) => r.name);
  const [sort, setSort] = useState<string | null>(null);
  const [vars, setVars] = useState<string[] | null>(null);
  const [resp, setResp] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  /** 커브 계열(커브 탭·설계공간 지도 공유, null = 첫 계열) */
  const [series, setSeries] = useState<string | null>(null);
  const sortKey = sort ?? (respNames[0] ? `${respNames[0]}:asc` : "doe");
  const pickVars = vars ?? table.parameters.slice(0, 1).map((p) => p.name);
  // 겹쳐 보기 중이면 응답 선택은 두 표에 공통인 응답만(§19.6, D3-62). 현재 선택이 공통이 아니면 첫 공통 응답으로
  const selectable = other ? commonResponses(table, other) : respNames;
  const pickResp = resp && selectable.includes(resp) ? resp : selectable[0] ?? null;
  const rows = useMemo(() => sortRtRows(table.rows, sortKey), [table, sortKey]);
  useEffect(() => {
    if (selected === null && rows.length) setSelected((rows.find((r) => isOkState(r.state)) ?? rows[0]).no);
  }, [rows, selected]);
  const toggleVar = (n: string) => setVars((v) => ((v ?? pickVars).includes(n) ? (v ?? pickVars).filter((x) => x !== n) : [...(v ?? pickVars), n]));
  // 현재 화면 선택 상태(출처·비교·변수·응답)를 그대로 보고서 쿼리로 — 빈 값은 서버가 같은 기본값 규칙으로 채운다
  const reportQuery: AnalysisReportQuery = { source: srcOf(table), id: table.origin.id, compare_source: other ? srcOf(other) : null, compare_id: other ? other.origin.id : null, vars: pickVars, resp: pickResp };
  return (
    <>
      <AnalysisTable
        table={table}
        sort={sortKey}
        onSort={setSort}
        pickVars={pickVars}
        onToggleVar={toggleVar}
        pickResp={pickResp}
        onPickResp={setResp}
        selectable={selectable}
        selected={selected}
        onSelect={setSelected}
        openHref={table.origin.kind === "predict_batch" ? `${studyBase}/stage/4/batch/${table.origin.id}` : null}
        report={
          <ReportButton
            load={() => reportApi.analysis(reportQuery)}
            fallbackName={`PAI_${study.folder_name}_analysis-${reportQuery.source}_${table.origin.id.slice(0, 8)}.html`}
            resetKey={JSON.stringify(reportQuery)}
          />
        }
      />
      <AnalysisContourCard table={table} selected={selected} />
      <AnalysisTabs table={table} other={other} pickVars={pickVars} pickResp={pickResp} selected={selected} onSelect={setSelected} series={series} onSeries={setSeries} />
    </>
  );
}
