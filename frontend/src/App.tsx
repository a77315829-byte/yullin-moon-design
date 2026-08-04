import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ChevronRight,
  FileDown,
  FileSpreadsheet,
  Inbox,
  Loader2,
  MailCheck,
  RefreshCw,
  Save,
  Search,
  Send,
  Settings,
  Sparkles,
  Upload,
  XCircle
} from "lucide-react";
import { api } from "./api";
import type { Draft, HistoryCandidate, MailDetail, MailItem, MailListItem, PriceCandidate, ReviewIssue } from "./types";

const STATUS_LABELS: Record<string, string> = {
  NEW: "신규",
  ANALYZING: "분석 중",
  REVIEW_REQUIRED: "검토 필요",
  READY_FOR_QUOTE: "견적 가능",
  QUOTE_CREATED: "견적 생성",
  APPROVED: "승인 완료",
  SENT: "발송 완료",
  FAILED: "처리 실패"
};

const NAV_ITEMS = [
  { key: "mail", label: "이메일", icon: Inbox },
  { key: "review", label: "검토 필요", icon: AlertTriangle },
  { key: "draft", label: "견적서", icon: FileSpreadsheet },
  { key: "settings", label: "설정", icon: Settings }
] as const;

type ViewKey = (typeof NAV_ITEMS)[number]["key"];

function money(value?: number | null) {
  return value == null ? "-" : `${value.toLocaleString("ko-KR")}원`;
}

function formatDate(value?: string | null) {
  if (!value) return "날짜 미확인";
  return new Date(value).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
}

function statusClass(status: string) {
  return `status status-${status.toLowerCase().replaceAll("_", "-")}`;
}

function App() {
  const [view, setView] = useState<ViewKey>("mail");
  const [mails, setMails] = useState<MailListItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mail, setMail] = useState<MailDetail | null>(null);
  const [prices, setPrices] = useState<PriceCandidate[]>([]);
  const [history, setHistory] = useState<HistoryCandidate[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [search, setSearch] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const statusFilter = view === "review" ? "REVIEW_REQUIRED" : undefined;

  async function loadMails(keepSelection = true) {
    try {
      const data = await api.listMails(statusFilter, search || undefined);
      setMails(data);
      if (!keepSelection || !selectedId || !data.some((item) => item.id === selectedId)) {
        setSelectedId(data[0]?.id ?? null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function loadMail(id: number) {
    setLoading(true);
    setError("");
    try {
      const detail = await api.getMail(id);
      setMail(detail);
      const [priceData, historyData] = await Promise.all([api.prices(id), api.history(id)]);
      setPrices(priceData);
      setHistory(historyData);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadDrafts() {
    try {
      setDrafts(await api.listDrafts());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    if (view === "draft") loadDrafts();
    else if (view !== "settings") loadMails(false);
  }, [view]);

  useEffect(() => {
    if (selectedId && view !== "draft" && view !== "settings") loadMail(selectedId);
    else setMail(null);
  }, [selectedId, view]);

  const blocking = useMemo(
    () => mail?.reviews.filter((issue) => !issue.resolved && issue.severity === "blocking") ?? [],
    [mail]
  );

  function showNotice(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3500);
  }

  async function runAction(action: () => Promise<unknown>, success: string, refresh = true) {
    setLoading(true);
    setError("");
    try {
      await action();
      showNotice(success);
      if (refresh && selectedId) {
        await loadMails();
        await loadMail(selectedId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function uploadEml(files: FileList | null) {
    if (!files?.length) return;
    await runAction(() => api.uploadEml(Array.from(files)), `${files.length}개 EML을 가져왔습니다.`, false);
    await loadMails(false);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">OM</div>
          <div>
            <strong>OPENMOON</strong>
            <span>AI 견적 업무 보조</span>
          </div>
        </div>
        <nav>
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
            <button key={key} className={view === key ? "nav-item active" : "nav-item"} onClick={() => setView(key)}>
              <Icon size={19} />
              <span>{label}</span>
              {key === "review" && mails.filter((item) => item.status === "REVIEW_REQUIRED").length > 0 && (
                <b className="nav-count">{mails.filter((item) => item.status === "REVIEW_REQUIRED").length}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <AlertTriangle size={17} />
          누락·충돌이 있는 메일은 자동 견적에서 제외됩니다.
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <h1>{NAV_ITEMS.find((item) => item.key === view)?.label}</h1>
            <p>{view === "mail" ? "고객 메일, AI 분석, 가격 근거를 한 화면에서 검토합니다." : view === "review" ? "필수정보가 누락된 메일만 모아 처리합니다." : view === "draft" ? "생성·승인·발송 상태를 관리합니다." : "초기 데이터와 연결 상태를 설정합니다."}</p>
          </div>
          <div className="top-actions">
            {(view === "mail" || view === "review") && (
              <>
                <input ref={fileRef} type="file" accept=".eml" multiple hidden onChange={(event) => uploadEml(event.target.files)} />
                <button className="button secondary" onClick={() => fileRef.current?.click()}><Upload size={17} /> EML 가져오기</button>
                <button className="button primary" onClick={() => runAction(() => api.syncMails(50), "메일 동기화가 완료되었습니다.")}><RefreshCw size={17} /> 메일 동기화</button>
              </>
            )}
          </div>
        </header>

        {notice && <div className="toast success"><CheckCircle2 size={18} />{notice}</div>}
        {error && <div className="toast error"><XCircle size={18} />{error}<button onClick={() => setError("")}>×</button></div>}

        {view === "draft" ? (
          <DraftView drafts={drafts} reload={loadDrafts} runAction={runAction} />
        ) : view === "settings" ? (
          <SettingsView runAction={runAction} />
        ) : (
          <div className="workbench">
            <section className="mail-column panel">
              <div className="panel-header">
                <div>
                  <strong>{view === "review" ? "검토 대기 메일" : "받은 메일"}</strong>
                  <span>{mails.length}건</span>
                </div>
                <button className="icon-button" onClick={() => loadMails()} title="새로고침"><RefreshCw size={17} /></button>
              </div>
              <div className="search-box"><Search size={16} /><input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && loadMails(false)} placeholder="기관, 담당자, 제목 검색" /></div>
              <div className="mail-list">
                {mails.map((item) => (
                  <button key={item.id} className={selectedId === item.id ? "mail-card selected" : "mail-card"} onClick={() => setSelectedId(item.id)}>
                    <div className="mail-card-top"><span className={statusClass(item.status)}>{STATUS_LABELS[item.status]}</span><time>{formatDate(item.original_sent_at)}</time></div>
                    <strong>{item.original_subject || item.outer_subject || "제목 없음"}</strong>
                    <p>{item.customer_organization || item.original_sender_name || item.original_sender_email || "고객 미확인"}</p>
                    <small>{item.summary || "아직 분석되지 않은 메일입니다."}</small>
                  </button>
                ))}
                {!mails.length && <div className="empty-state"><Inbox size={32} /><p>표시할 메일이 없습니다.</p></div>}
              </div>
            </section>

            <section className="mail-view panel">
              {loading && !mail ? <Loading /> : mail ? <OriginalMail mail={mail} /> : <EmptySelect />}
            </section>

            <section className="analysis-view panel">
              {mail ? (
                <AnalysisPanel
                  mail={mail}
                  prices={prices}
                  blocking={blocking}
                  onAnalyze={() => runAction(() => api.analyzeMail(mail.id), "AI 분석이 완료되었습니다.")}
                  onSave={(payload) => runAction(() => api.saveAnalysis(mail.id, payload), "분석 내용을 저장했습니다.")}
                  onResolve={(issue, value) => runAction(() => api.resolveReview(issue.id, value), "검토 항목을 반영했습니다.")}
                  onCreate={() => runAction(() => api.createDraft(mail.id), "견적서 초안을 생성했습니다.")}
                  loading={loading}
                />
              ) : <EmptySelect />}
            </section>

            <section className="bottom-panel panel">
              <HistoryAndPricing history={history} prices={prices} />
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

function OriginalMail({ mail }: { mail: MailDetail }) {
  return (
    <div className="column-content">
      <div className="panel-header sticky"><div><strong>원본 고객 메일</strong><span>전달 {mail.forward_depth || 0}단계</span></div></div>
      <div className="mail-meta">
        <h2>{mail.original_subject || mail.outer_subject}</h2>
        <dl><dt>보낸 사람</dt><dd>{mail.original_sender_name} &lt;{mail.original_sender_email}&gt;</dd><dt>받는 사람</dt><dd>{mail.original_recipient || "-"}</dd><dt>요청 시각</dt><dd>{formatDate(mail.original_sent_at)}</dd></dl>
      </div>
      <article className="mail-body">{mail.original_body || "본문이 없습니다."}</article>
      <div className="attachment-section">
        <h3>첨부파일 <span>{mail.attachments.length}</span></h3>
        {mail.attachments.map((attachment) => (
          <a key={attachment.id} className="attachment-card" href={`/api/mails/attachments/${attachment.id}/file`} target="_blank" rel="noreferrer">
            <FileDown size={18} /><div><strong>{attachment.filename}</strong><small>{(attachment.size_bytes / 1024).toFixed(1)}KB · {attachment.status}</small></div><ChevronRight size={17} />
          </a>
        ))}
        {!mail.attachments.length && <p className="muted">첨부파일 없음</p>}
      </div>
    </div>
  );
}

function AnalysisPanel({ mail, prices, blocking, onAnalyze, onSave, onResolve, onCreate, loading }: {
  mail: MailDetail;
  prices: PriceCandidate[];
  blocking: ReviewIssue[];
  onAnalyze: () => void;
  onSave: (payload: unknown) => void;
  onResolve: (issue: ReviewIssue, value: unknown) => void;
  onCreate: () => void;
  loading: boolean;
}) {
  const [form, setForm] = useState<MailDetail>(mail);
  useEffect(() => setForm(mail), [mail]);

  function patchItem(index: number, patch: Partial<MailItem>) {
    const items = [...form.items];
    items[index] = { ...items[index], ...patch };
    setForm({ ...form, items });
  }

  function save() {
    onSave({
      customer_organization: form.customer_organization,
      customer_department: form.customer_department,
      customer_name: form.customer_name,
      customer_phone: form.customer_phone,
      customer_email: form.customer_email,
      delivery_place: form.delivery_place,
      payment_terms: form.payment_terms,
      requested_date: form.requested_date,
      request_types: form.request_types,
      commitment_status: form.commitment_status,
      summary: form.summary,
      reason: form.reason,
      items: form.items
    });
  }

  return (
    <div className="column-content analysis-content">
      <div className="panel-header sticky"><div><strong>AI 분석 및 최종 검토</strong><span className={statusClass(mail.status)}>{STATUS_LABELS[mail.status]}</span></div><button className="button compact" onClick={onAnalyze} disabled={loading}>{loading ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />} 분석</button></div>

      {mail.reviews.filter((issue) => !issue.resolved).length > 0 && (
        <div className="review-box">
          <h3><AlertTriangle size={18} /> 검토 필요 {mail.reviews.filter((issue) => !issue.resolved).length}건</h3>
          {mail.reviews.filter((issue) => !issue.resolved).map((issue) => <ReviewRow key={issue.id} issue={issue} onResolve={onResolve} />)}
        </div>
      )}

      <div className="form-section">
        <h3>고객 정보</h3>
        <div className="form-grid two">
          <Field label="기관명" value={form.customer_organization} onChange={(value) => setForm({ ...form, customer_organization: value })} />
          <Field label="담당자" value={form.customer_name} onChange={(value) => setForm({ ...form, customer_name: value })} />
          <Field label="이메일" value={form.customer_email} onChange={(value) => setForm({ ...form, customer_email: value })} />
          <Field label="전화번호" value={form.customer_phone} onChange={(value) => setForm({ ...form, customer_phone: value })} />
          <Field label="납품 장소" value={form.delivery_place} onChange={(value) => setForm({ ...form, delivery_place: value })} />
          <Field label="희망 일정" value={form.requested_date} onChange={(value) => setForm({ ...form, requested_date: value })} />
        </div>
      </div>

      <div className="form-section">
        <div className="section-title"><h3>주문 품목</h3><button className="text-button" onClick={() => setForm({ ...form, items: [...form.items, { product_name: "", evidence: {} }] })}>+ 품목 추가</button></div>
        {form.items.map((item, index) => (
          <div className="item-editor" key={item.id ?? `new-${index}`}>
            <div className="item-number">{index + 1}</div>
            <div className="form-grid two">
              <Field label="품목" value={item.product_name} onChange={(value) => patchItem(index, { product_name: value })} />
              <Field label="규격 설명" value={item.specification} onChange={(value) => patchItem(index, { specification: value })} />
              <NumberField label="가로(mm)" value={item.width_mm} onChange={(value) => patchItem(index, { width_mm: value })} />
              <NumberField label="세로(mm)" value={item.height_mm} onChange={(value) => patchItem(index, { height_mm: value })} />
              <NumberField label="수량" value={item.quantity} onChange={(value) => patchItem(index, { quantity: value })} />
              <Field label="단위" value={item.unit} onChange={(value) => patchItem(index, { unit: value })} />
              <Field label="용지" value={item.paper} onChange={(value) => patchItem(index, { paper: value })} />
              <Field label="단면·양면" value={item.print_sides} onChange={(value) => patchItem(index, { print_sides: value })} />
              <Field label="재질" value={item.material} onChange={(value) => patchItem(index, { material: value })} />
              <NumberField label="확정 단가" value={item.unit_price} onChange={(value) => patchItem(index, { unit_price: value == null ? null : Math.round(value) })} />
            </div>
            <label className="field full"><span>디자인·문구 요청</span><textarea value={item.design_request || item.detail_text || ""} onChange={(e) => patchItem(index, { design_request: e.target.value })} /></label>
          </div>
        ))}
        {!form.items.length && <p className="muted">추출된 품목이 없습니다. AI 분석을 실행하거나 품목을 추가하세요.</p>}
      </div>

      <div className="form-section"><h3>분석 요약</h3><textarea className="summary-input" value={form.summary || ""} onChange={(e) => setForm({ ...form, summary: e.target.value })} /></div>
      <div className="action-bar"><button className="button secondary" onClick={save}><Save size={17} /> 수정 저장</button><button className="button primary" disabled={blocking.length > 0 || !form.items.length} onClick={onCreate}><FileSpreadsheet size={17} /> 견적서 생성</button></div>
      {blocking.length > 0 && <p className="blocking-note">필수 검토 {blocking.length}건을 해결해야 견적서를 생성할 수 있습니다.</p>}
    </div>
  );
}

function ReviewRow({ issue, onResolve }: { issue: ReviewIssue; onResolve: (issue: ReviewIssue, value: unknown) => void }) {
  const [value, setValue] = useState("");
  const suggestion = issue.suggestions[0] as Record<string, unknown> | undefined;
  const suggestedValue = suggestion && typeof suggestion === "object" ? suggestion.value : suggestion;
  return (
    <div className={`review-row ${issue.severity}`}>
      <div><strong>{issue.message}</strong><small>{issue.code}</small></div>
      <div className="review-resolve">
        {suggestedValue != null && <button className="suggestion-chip" onClick={() => onResolve(issue, suggestedValue)}>추천 {String(suggestedValue)}</button>}
        <input placeholder="직접 입력" value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="icon-button" disabled={!value} onClick={() => onResolve(issue, Number.isNaN(Number(value)) ? value : Number(value))}><CheckCircle2 size={17} /></button>
      </div>
    </div>
  );
}

function HistoryAndPricing({ history, prices }: { history: HistoryCandidate[]; prices: PriceCandidate[] }) {
  const [tab, setTab] = useState<"history" | "price">("history");
  return (
    <div className="bottom-content">
      <div className="bottom-tabs"><button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>동일 고객 과거 견적 <span>{history.length}</span></button><button className={tab === "price" ? "active" : ""} onClick={() => setTab("price")}>현재 단가 후보 <span>{prices.length}</span></button></div>
      <div className="table-wrap">
        {tab === "history" ? (
          <table><thead><tr><th>견적일</th><th>품목</th><th>규격</th><th>수량</th><th>단가</th><th>근거</th></tr></thead><tbody>{history.map((row, index) => <tr key={`${row.quotation_id}-${index}`}><td>{row.quotation_date || "-"}</td><td>{row.product_name}</td><td>{row.specification || "-"}</td><td>{row.quantity ?? "-"}</td><td>{money(row.unit_price)}</td><td title={row.source_file}>{row.source_sheet}</td></tr>)}{!history.length && <tr><td colSpan={6} className="empty-cell">연결된 과거 견적이 없습니다.</td></tr>}</tbody></table>
        ) : (
          <table><thead><tr><th>품목</th><th>금액</th><th>일치</th><th>VAT</th><th>근거 셀</th><th>설명</th></tr></thead><tbody>{prices.map((row, index) => <tr key={`${row.item_id}-${index}`}><td>{row.product_name}</td><td>{money(row.amount)}</td><td><span className={row.exact ? "match exact" : "match candidate"}>{row.exact ? "정확" : "후보"}</span></td><td>{row.vat || "미상"}</td><td>{row.source_sheet}!{row.source_cell}</td><td>{row.context || row.reason}</td></tr>)}{!prices.length && <tr><td colSpan={6} className="empty-cell">가격 후보가 없습니다.</td></tr>}</tbody></table>
        )}
      </div>
    </div>
  );
}

function DraftView({ drafts, reload, runAction }: { drafts: Draft[]; reload: () => Promise<void>; runAction: (action: () => Promise<unknown>, success: string, refresh?: boolean) => Promise<void> }) {
  return <div className="page-card"><div className="page-card-header"><div><h2>견적서 목록</h2><p>승인 전에는 실제 메일 발송이 불가능합니다.</p></div><button className="icon-button" onClick={reload}><RefreshCw size={18} /></button></div><div className="draft-grid">{drafts.map((draft) => <article className="draft-card" key={draft.id}><div className="draft-top"><span className={`status status-${draft.status.toLowerCase()}`}>{draft.status}</span><small>#{draft.id}</small></div><h3>{draft.customer_name}</h3><p>{draft.items.map((item) => item.product_name).join(", ") || "품목 없음"}</p><strong>{money(draft.total_amount)}</strong><div className="draft-actions"><a className="button secondary compact" href={`/api/quotations/${draft.id}/file`}><FileDown size={16} /> Excel</a>{draft.status === "DRAFT" && <button className="button primary compact" onClick={() => runAction(() => api.approveDraft(draft.id), "견적서를 승인했습니다.", false).then(reload)}><CheckCircle2 size={16} /> 승인</button>}{draft.status === "APPROVED" && <button className="button danger compact" onClick={() => runAction(() => api.sendDraft(draft.id), "메일을 발송했습니다.", false).then(reload)}><Send size={16} /> 발송</button>}</div>{draft.error_message && <small className="error-text">{draft.error_message}</small>}</article>)}{!drafts.length && <div className="empty-state wide"><Archive size={38} /><p>생성된 견적서가 없습니다.</p></div>}</div></div>;
}

function SettingsView({ runAction }: { runAction: (action: () => Promise<unknown>, success: string, refresh?: boolean) => Promise<void> }) {
  const [historyPath, setHistoryPath] = useState("");
  const [status, setStatus] = useState<Record<string, unknown>>({});
  const [paths, setPaths] = useState<Record<string, string>>({});
  useEffect(() => { api.settingsStatus().then(setStatus); api.settingsPaths().then(setPaths); }, []);
  return <div className="settings-layout"><section className="page-card"><h2>연결 상태</h2><div className="status-grid"><StatusTile label="OpenAI" enabled={Boolean(status.openai_configured)} /><StatusTile label="Daum 메일" enabled={Boolean(status.mail_configured)} /><StatusTile label="실제 발송" enabled={Boolean(status.live_send_enabled)} warning /></div><div className="path-list">{Object.entries(paths).map(([key, value]) => <div key={key}><span>{key}</span><code>{value || "미설정"}</code></div>)}</div></section><section className="page-card"><h2>초기 데이터 가져오기</h2><div className="settings-block"><h3>현재 단가표</h3><p>AI_가격후보, AI_규칙, AI_용어사전과 현수막 규격표를 DB로 변환합니다.</p><button className="button primary" onClick={() => runAction(() => api.importPriceTable(), "단가표 가져오기가 완료되었습니다.", false)}><FileSpreadsheet size={17} /> 기본 단가표 가져오기</button></div><div className="settings-block"><h3>과거 견적 전체 폴더</h3><p>2025·2026 폴더를 포함하는 상위 경로를 입력하세요. 원본 파일은 변경하지 않습니다.</p><input className="path-input" value={historyPath} onChange={(e) => setHistoryPath(e.target.value)} placeholder="D:\열린문디자인\견적서" /><button className="button primary" disabled={!historyPath} onClick={() => runAction(() => api.importHistory(historyPath), "전체 견적 이력 가져오기가 완료되었습니다.", false)}><Archive size={17} /> 전체 이력 가져오기</button></div></section></div>;
}

function StatusTile({ label, enabled, warning = false }: { label: string; enabled: boolean; warning?: boolean }) { return <div className={`status-tile ${enabled ? (warning ? "warning" : "enabled") : "disabled"}`}>{enabled ? <CheckCircle2 size={22} /> : <XCircle size={22} />}<div><strong>{label}</strong><span>{enabled ? "설정됨" : "미설정"}</span></div></div>; }
function Field({ label, value, onChange }: { label: string; value?: string | null; onChange: (value: string) => void }) { return <label className="field"><span>{label}</span><input value={value || ""} onChange={(e) => onChange(e.target.value)} /></label>; }
function NumberField({ label, value, onChange }: { label: string; value?: number | null; onChange: (value: number | null) => void }) { return <label className="field"><span>{label}</span><input type="number" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} /></label>; }
function Loading() { return <div className="empty-state"><Loader2 className="spin" size={36} /><p>불러오는 중입니다.</p></div>; }
function EmptySelect() { return <div className="empty-state"><MailCheck size={38} /><p>왼쪽에서 메일을 선택하세요.</p></div>; }

export default App;
