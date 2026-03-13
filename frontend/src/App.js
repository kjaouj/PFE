import { useState, useEffect, useRef } from "react";
import "./App.css";
import { api, API_BASE } from "./api";

function IconFolder() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H10l2 2h6.5A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

function IconSun() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 2.5v2.2M12 19.3v2.2M4.9 4.9l1.5 1.5M17.6 17.6l1.5 1.5M2.5 12h2.2M19.3 12h2.2M4.9 19.1l1.5-1.5M17.6 6.4l1.5-1.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function IconMoon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M16.8 14.8A7 7 0 0 1 9.2 5.7a8 8 0 1 0 9.1 9.1 6.3 6.3 0 0 1-1.5 0Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

function IconChevron({ direction = "right" }) {
  const rotation = {
    right: "0deg",
    left: "180deg",
    down: "90deg",
  }[direction];

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" style={{ transform: `rotate(${rotation})` }}>
      <path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function App() {
  const [session, setSession] = useState("Research Session");
  const [sessions, setSessions] = useState([]);
  const [newSessionName, setNewSessionName] = useState("");
  const [isSessionsOpen, setIsSessionsOpen] = useState(true);
  const [isSidebarVisible, setIsSidebarVisible] = useState(true);
  const [pdfs, setPdfs] = useState([]);
  const [selectedPdfs, setSelectedPdfs] = useState([]);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [status, setStatus] = useState("");
  const [mode, setMode] = useState("qa");
  const [loading, setLoading] = useState(false);
  const [theme, setTheme] = useState(localStorage.getItem("theme") || "dark");
  const [pdfViewer, setPdfViewer] = useState(null);
  const [highlights, setHighlights] = useState([]);
  const [highlightNote, setHighlightNote] = useState("");
  const [highlightTags, setHighlightTags] = useState("");
  const [highlightSearch, setHighlightSearch] = useState("");
  const [highlightSearchResults, setHighlightSearchResults] = useState([]);
  const [highlightSearchLoading, setHighlightSearchLoading] = useState(false);
  const [isPdfDrawerFullscreen, setIsPdfDrawerFullscreen] = useState(false);
  const [externalLoading, setExternalLoading] = useState(false);
  const [externalError, setExternalError] = useState("");
  const fileInputRef = useRef(null);
  const chatEndRef = useRef(null);

  const externalSources = [
    { id: "arxiv", label: "arXiv", hint: "Computer science, physics and math preprints" },
    { id: "pubmed", label: "PubMed", hint: "Biomedical and life-science publications" },
    { id: "semanticscholar", label: "Semantic Scholar", hint: "Citation graph and broad metadata search" },
    { id: "acl", label: "ACL", hint: "NLP and computational linguistics papers" },
    { id: "medrxiv", label: "medRxiv", hint: "Health-science preprints and early findings" },
  ];

  // Theme management
  useEffect(() => {
    localStorage.setItem("theme", theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === "dark" ? "light" : "dark");
  };


  // Initial load
  useEffect(() => {
    loadSessions();
  }, []);

  // Auto-load PDFs and history when session changes
  useEffect(() => {
    if (session) {
      loadPdfs();
      loadHistory();
    }
    if (mode === 'monitoring') {
      loadMetrics();
    }
  }, [session, mode]);

  // Scroll to bottom of chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (pdfViewer?.filename) {
      loadHighlightsForDocument(pdfViewer.filename);
    }
  }, [pdfViewer?.filename, pdfs]);

  useEffect(() => {
    const q = highlightSearch.trim();
    if (!session || !q) {
      setHighlightSearchResults([]);
      setHighlightSearchLoading(false);
      return;
    }

    setHighlightSearchLoading(true);
    const timer = setTimeout(() => {
      runHighlightSearch(q);
    }, 350);

    return () => clearTimeout(timer);
  }, [highlightSearch, session]);

  const loadSessions = async () => {
    try {
      const data = await api.listSessions();
      setSessions(data || []);
    } catch (err) {
      console.error("Failed to load sessions", err);
    }
  };

  const loadHistory = async () => {
    try {
      const data = await api.listHistory(session);
      setMessages(data?.history || []);
    } catch (err) {
      console.error("Failed to load history", err);
    }
  };

  const loadPdfs = async () => {
    try {
      const data = await api.listPdfs(session);
      setPdfs(data?.pdfs || []);
    } catch (err) {
      console.error("Failed to load PDFs", err);
    }
  };

  const loadMetrics = async () => {
    try {
      const data = await api.listMetrics();
      setMetrics(data);
    } catch (err) {
      console.error("Failed to load metrics", err);
    }
  };

  const normalizeForMatch = (text = "") =>
    text
      .toLowerCase()
      .replace(/[^\w\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();

  const choosePrecisePhrase = (snippet, pageText) => {
    const cleanSnippet = (snippet || "").replace(/\s+/g, " ").trim();
    const cleanPage = normalizeForMatch(pageText || "");
    if (!cleanSnippet || !cleanPage) return "";

    const words = cleanSnippet.split(" ").filter(Boolean);
    if (words.length < 4) return "";

    const windowSizes = [16, 14, 12, 10, 8, 6];
    for (const size of windowSizes) {
      if (words.length < size) continue;
      for (let i = 0; i <= words.length - size; i++) {
        const phrase = words.slice(i, i + size).join(" ").trim();
        const phraseNorm = normalizeForMatch(phrase);
        if (phraseNorm.length < 24) continue;
        if (cleanPage.includes(phraseNorm)) {
          return phrase;
        }
      }
    }

    return "";
  };

  const chooseFallbackSearch = (snippet) => {
    const cleanSnippet = normalizeForMatch(snippet || "");
    if (!cleanSnippet) return "";

    const words = cleanSnippet.split(" ").filter(Boolean);
    if (words.length === 0) return "";

    return words.slice(0, 12).join(" ");
  };

  const openCitationViewer = async (citation) => {
    const filename = citation.source;
    const page = citation.pageOneIndexed
      ? Number(citation.page || 1)
      : Number(citation.page || 0) + 1;
    const snippet = (citation.snippet || "").trim();
    const docUrl = `${API_BASE}/media/pdfs/${encodeURIComponent(filename)}`;

    let precisePhrase = "";
    let textPreview = "";
    let contentType = "pdf";
    const doc = pdfs.find((p) => p.filename === filename);
    const isSummaryOnly = Boolean(doc?.error_message?.includes("Summary-only"));
    const isPdfFilename = filename?.toLowerCase().endsWith(".pdf");

    if (doc) {
      try {
        const payload = await api.getDocumentPageText(doc.id, page);
        textPreview = payload?.text || "";
        contentType = payload?.content_type || "pdf";
        precisePhrase = choosePrecisePhrase(snippet, payload?.text || "");
      } catch (err) {
        console.error("Failed fetching page text for precise highlight", err);
      }
    }

    const searchQuery = precisePhrase || chooseFallbackSearch(snippet);
    const usePhraseMatch = Boolean(precisePhrase);
    const shouldUsePdfViewer = isPdfFilename && !isSummaryOnly && contentType === "pdf";
    const viewerUrl = shouldUsePdfViewer
      ? `https://mozilla.github.io/pdf.js/web/viewer.html?file=${encodeURIComponent(docUrl)}#page=${page}${searchQuery ? `&search=${encodeURIComponent(searchQuery)}${usePhraseMatch ? "&phrase=true" : ""}` : ""}`
      : "";

    setPdfViewer({
      filename,
      page,
      snippet,
      viewerUrl,
      textPreview,
      mode: shouldUsePdfViewer ? "pdf" : "text",
      precisePhrase,
    });
    setIsPdfDrawerFullscreen(false);
  };

  const loadHighlightsForDocument = async (filename) => {
    const doc = pdfs.find((p) => p.filename === filename);
    if (!doc) return setHighlights([]);

    try {
      const data = await api.listHighlights(doc.id);
      setHighlights(data?.highlights || []);
    } catch (err) {
      console.error("Failed to load highlights", err);
    }
  };

  const createHighlightFromCitation = async () => {
    if (!pdfViewer?.filename || !pdfViewer?.snippet) return;
    const doc = pdfs.find((p) => p.filename === pdfViewer.filename);
    if (!doc) return;

    const tags = highlightTags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    try {
      await api.createHighlight({
        document_id: doc.id,
        page: pdfViewer.page,
        start_offset: 0,
        end_offset: pdfViewer.snippet.length,
        text: pdfViewer.snippet,
        note: highlightNote,
        tags,
      });
      setHighlightNote("");
      setHighlightTags("");
      await loadHighlightsForDocument(pdfViewer.filename);
      setStatus("Highlight saved");
    } catch (err) {
      setStatus("Failed to save highlight");
    }
  };

  const deleteHighlight = async (highlightId) => {
    try {
      await api.deleteHighlight(highlightId);
      if (pdfViewer?.filename) {
        await loadHighlightsForDocument(pdfViewer.filename);
      }
    } catch (err) {
      console.error("Failed to delete highlight", err);
    }
  };

  const runHighlightSearch = async (query) => {
    if (!query || !session) return;
    try {
      const data = await api.searchHighlights({ session, q: query });
      setHighlightSearchResults(data?.results || []);
    } catch (err) {
      console.error("Highlight search failed", err);
      setHighlightSearchResults([]);
    } finally {
      setHighlightSearchLoading(false);
    }
  };

  const searchMyHighlights = async (e) => {
    e?.preventDefault();
    const q = highlightSearch.trim();
    if (!q || !session) return;
    setHighlightSearchLoading(true);
    await runHighlightSearch(q);
  };

  const handleCreateSession = async (e) => {
    e?.preventDefault();
    if (!newSessionName.trim()) return;

    setStatus("Creating session...");
    try {
      await api.createSession(newSessionName);
      setSession(newSessionName);
      setNewSessionName("");
      await loadSessions();
      setStatus("Session ready");
    } catch (err) {
      setStatus("Error creating session");
    }
  };

  const deleteSession = async (e, name) => {
    e.stopPropagation();
    if (!window.confirm(`Delete entire workflow for "${name}"? This cannot be undone.`)) return;

    setStatus("Deleting session data...");
    try {
      await api.deleteSession(name);
      if (session === name) {
        setSession("");
        setPdfs([]);
        setMessages([]);
      }
      await loadSessions();
      setStatus("Session deleted");
    } catch (err) {
      console.error("Delete failed", err);
      setStatus("Delete failed");
    }
  };

  const [arxivQuery, setArxivQuery] = useState("");
  const [searchSource, setSearchSource] = useState("arxiv"); // New: arxiv, pubmed, semanticscholar
  const [arxivResults, setArxivResults] = useState([]);
  const [isArxivOpen, setIsArxivOpen] = useState(false);
  const [previewId, setPreviewId] = useState(null);
  const activeExternalSource = externalSources.find((src) => src.id === searchSource) || externalSources[0];

  // Poll for processing PDFs
  useEffect(() => {
    const processingPdfs = pdfs.filter(p => p.status === 'UPLOADED' || p.status === 'PROCESSING');
    if (processingPdfs.length > 0) {
      const interval = setInterval(() => {
        loadPdfs();
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [pdfs]);

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);
    formData.append("session", session);

    setStatus("Uploading...");
    setLoading(true);

    try {
      const data = await api.uploadPdf(formData);
      setStatus(data?.message || "Upload initiated");
      loadPdfs();
    } catch (err) {
      setStatus("Upload failed");
    } finally {
      setLoading(false);
    }
  };

  const searchExternal = async (e) => {
    e?.preventDefault();
    if (!arxivQuery.trim()) return;
    setStatus(`Searching ${searchSource.toUpperCase()}...`);
    setExternalLoading(true);
    setExternalError("");
    try {
      const data = await api.searchExternal({ q: arxivQuery, source: searchSource });
      setArxivResults(data?.results || []);
      setStatus(data?.results?.length > 0 ? "Search complete" : "No results found");
    } catch (err) {
      if (err.status === 429) {
        setExternalError(`${searchSource.toUpperCase()}: Too many requests. Please wait.`);
      } else {
        setExternalError(err?.message || "External search failed");
      }
      setStatus("External search failed");
      setArxivResults([]);
    } finally {
      setExternalLoading(false);
    }
  };

  const importExternal = async (id) => {
    setStatus(`Importing from ${searchSource.toUpperCase()}...`);
    try {
      await api.importExternal({ id, source: searchSource, session });
      setStatus("Import initiated");
      loadPdfs();
    } catch (err) {
      setStatus("Import failed: " + (err?.message || "Unknown"));
    }
  };

  const askQuestion = async (e) => {
    e?.preventDefault();
    if (!question.trim() || loading) return;

    const userMsg = { role: "user", text: `${mode === 'qa' ? '' : '[' + mode.toUpperCase() + '] '}${question}` };
    setMessages(prev => [...prev, userMsg]);
    setQuestion("");
    setLoading(true);
    setStatus("Thinking...");

    try {
      const data = await api.ask({
        question: question,
        sources: selectedPdfs,
        session,
        mode: mode,
      });

      if (mode === "compare") {
        setMessages(prev => [...prev, {
          role: "assistant",
          text: `Comparison for: "${question}"`,
          comparison: data,
          citations: data.citations || [],
        }]);
      } else if (mode === "lit_review") {
        setMessages(prev => [...prev, {
          role: "assistant",
          text: data.content,
          title: data.title || "Literature Review"
        }]);
      } else {
        setMessages(prev => [...prev, {
          role: "assistant",
          text: data.answer,
          citations: data.citations || []
        }]);
      }
      setStatus("Ready");
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        text: "Error: " + err.message,
        isError: true
      }]);
      setStatus("Error occurred");
    } finally {
      setLoading(false);
    }
  };

  const togglePdf = (filename) => {
    const pdf = pdfs.find(p => p.filename === filename);
    // Be resilient: if status is missing, assume it's okay (indexed)
    const isReady = !pdf?.status || pdf.status === 'INDEXED';
    if (!isReady) return;

    setSelectedPdfs(prev =>
      prev.includes(filename)
        ? prev.filter(f => f !== filename)
        : [...prev, filename]
    );
  };

  const deletePdf = async (e, filename) => {
    e.stopPropagation();
    if (!window.confirm(`Remove ${filename} from this session?`)) return;

    try {
      await api.deletePdf({ session, filename });
      loadPdfs();
      setSelectedPdfs(prev => prev.filter(p => p !== filename));
    } catch (err) {
      console.error("Delete failed", err);
    }
  };

  const retryPdfIngestion = async (e, pdf) => {
    e.stopPropagation();
    setStatus(`Retrying ingestion for ${pdf.filename}...`);
    try {
      const data = await api.retryDocument(pdf.id);
      setStatus(data?.message || "Retry initiated");
      await loadPdfs();
    } catch (err) {
      setStatus(err?.message || "Retry failed");
    }
  };

  return (
    <div className={`app-layout ${theme === 'light' ? 'light-mode' : ''} ${isSidebarVisible ? '' : 'sidebar-hidden'}`}>
      {/* Sidebar */}
      {isSidebarVisible && <aside className="sidebar">
        <div className="sidebar-header">
          <div style={{ display: 'flex', alignItems: 'center', width: '100%' }}>
            <h1>Scientific Navigator</h1>
            <button
              className="theme-toggle"
              onClick={toggleTheme}
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            >
              {theme === "dark" ? <IconSun /> : <IconMoon />}
            </button>
          </div>
        </div>

        <div className="sidebar-scroll">
          <div className="session-config">
            <span className="section-label" onClick={() => setIsSessionsOpen(!isSessionsOpen)}>
              Your Sessions
              <span className={`toggle-icon ${isSessionsOpen ? 'open' : ''}`}>{">"}</span>
            </span>

            <div className={`session-list ${isSessionsOpen ? '' : 'collapsed'}`}
              style={{ maxHeight: isSessionsOpen ? '1000px' : '0' }}>
              {sessions.map((s, i) => (
                <div
                  key={i}
                  className={`session-item ${session === s.name ? 'active' : ''}`}
                  onClick={() => setSession(s.name)}
                >
                  <div className="session-content">
                    <span className="session-item-icon" aria-hidden="true">
                      <IconFolder />
                    </span>
                    {s.name}
                  </div>
                  <button
                    className="delete-session-btn"
                    onClick={(e) => deleteSession(e, s.name)}
                    title="Delete Session"
                  >
                    &times;
                  </button>
                </div>
              ))}
            </div>

            <span className="section-label">New Session</span>
            <form className="input-group" onSubmit={handleCreateSession}>
              <input
                type="text"
                value={newSessionName}
                onChange={(e) => setNewSessionName(e.target.value)}
                placeholder="Session name..."
              />
              <button type="submit" className="btn-icon">
                +
              </button>
            </form>
          </div>

          <div className="source-management">
            <div className="section-header">
              <span className="section-label">External Search</span>
              <button className="text-btn" onClick={() => setIsArxivOpen(!isArxivOpen)}>
                {isArxivOpen ? 'Close' : 'Open'}
              </button>
            </div>

            {isArxivOpen && (
              <div className="arxiv-search-box">
                <div className="source-tabs">
                  {externalSources.map((src) => (
                    <button
                      key={src.id}
                      className={`source-tab ${searchSource === src.id ? "active" : ""}`}
                      onClick={() => {
                        setSearchSource(src.id);
                        setArxivResults([]);
                        setPreviewId(null);
                        setExternalError("");
                      }}
                    >
                      {src.label}
                    </button>
                  ))}

                </div>
                <p className="external-source-hint">{activeExternalSource.hint}</p>
                <form className="input-group" onSubmit={searchExternal}>
                  <input
                    type="text"
                    value={arxivQuery}
                    onChange={(e) => setArxivQuery(e.target.value)}
                    placeholder={`Search ${activeExternalSource.label}...`}
                  />
                  <button type="submit" className="btn-icon" disabled={externalLoading}>
                    {externalLoading ? "..." : "Go"}
                  </button>
                </form>
                {externalError && <p className="external-error">{externalError}</p>}
                <div className="arxiv-results">
                  {arxivResults.map((res, i) => (
                    <div key={i} className={`arxiv-result-item ${previewId === res.id ? 'expanded' : ''}`}>
                      <div className="arxiv-res-header" onClick={() => setPreviewId(previewId === res.id ? null : res.id)}>
                        <p className="arxiv-res-title">{res.title}</p>
                        <span className="expand-chevron">{previewId === res.id ? "v" : ">"}</span>
                      </div>

                      {previewId === res.id && (
                        <div className="arxiv-res-preview">
                          <p className="arxiv-meta"><strong>Authors:</strong> {res.authors?.join(', ')}</p>
                          <p className="arxiv-meta"><strong>Date:</strong> {res.date || "n/a"}</p>
                          <div className="arxiv-abstract-container">
                            <strong>Abstract:</strong>
                            <p className="arxiv-abstract">{res.abstract || "No abstract available."}</p>
                          </div>
                          <div className="arxiv-actions">
                            <a
                              href={res.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="arxiv-link-btn"
                              onClick={(e) => e.stopPropagation()}
                            >
                              Open Paper
                            </a>
                            <button
                              className="mini-btn"
                              onClick={(e) => {
                                e.stopPropagation();
                                importExternal(res.id);
                              }}
                            >
                              Import
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="section-header">
              <span className="section-label">Sources ({pdfs.length})</span>
              {pdfs.length > 0 && (
                <button
                  className="text-btn"
                  onClick={() => setSelectedPdfs(
                    selectedPdfs.length === pdfs.length ? [] : pdfs.map(p => p.filename)
                  )}
                >
                  {selectedPdfs.length === pdfs.length ? 'Deselect All' : 'Select All'}
                </button>
              )}
            </div>

            <div className="upload-zone" onClick={() => fileInputRef.current.click()}>
              <p>+ Add Document</p>
              <input
                type="file"
                className="hide-input"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept=".pdf"
              />
            </div>

            <div className="source-list">
              {pdfs.map((pdf, i) => {
                const isReady = !pdf.status || pdf.status === 'INDEXED';
                return (
                  <div
                    key={i}
                    className={`source-item ${selectedPdfs.includes(pdf.filename) ? 'selected' : ''} ${!isReady ? 'disabled' : ''}`}
                    onClick={() => togglePdf(pdf.filename)}
                  >
                    <input
                      type="checkbox"
                      checked={selectedPdfs.includes(pdf.filename)}
                      disabled={!isReady}
                      readOnly
                    />
                    <div className="source-info">
                      <span className="source-title" title={pdf.title || pdf.filename}>
                        {pdf.title || "Untitled Paper"}
                      </span>
                      <span className="source-meta">
                        {pdf.filename} - <span className={`status-badge ${(pdf.error_message?.includes('Summary-only') ? 'summary' : (pdf.status || 'INDEXED').toLowerCase())}`}>
                          {pdf.error_message?.includes('Summary-only') ? 'SUMMARY' : (pdf.status || 'INDEXED')}
                        </span>
                      </span>
                    </div>
                    <div className="source-actions">
                      {pdf.status === "FAILED" && (
                        <button
                          className="retry-source-btn"
                          onClick={(e) => retryPdfIngestion(e, pdf)}
                          title="Retry ingestion"
                        >
                          Retry
                        </button>
                      )}
                      <button
                        className="delete-source-btn"
                        onClick={(e) => deletePdf(e, pdf.filename)}
                        title="Delete source"
                      >
                        &times;
                      </button>
                    </div>
                  </div>
                );
              })}
              {pdfs.length === 0 && (
                <p className="muted" style={{ textAlign: 'center', fontSize: '0.8rem' }}>
                  No documents in this session.
                </p>
              )}
            </div>
          </div>
        </div>
      </aside>}

      <button
        className={`sidebar-edge-toggle ${isSidebarVisible ? "visible" : "hidden"}`}
        onClick={() => setIsSidebarVisible((v) => !v)}
        title={isSidebarVisible ? "Hide sidebar" : "Show sidebar"}
        aria-label={isSidebarVisible ? "Hide sidebar" : "Show sidebar"}
      >
        <IconChevron direction={isSidebarVisible ? "left" : "right"} />
      </button>

      {/* Main Content */}
      <main className="main-content">
        <div className="mode-selector">
          {['qa', 'compare', 'lit_review', 'monitoring'].map(m => (
            <button
              key={m}
              className={`mode-btn ${mode === m ? 'active' : ''}`}
              onClick={() => setMode(m)}
            >
              {m.toUpperCase().replace('_', ' ')}
            </button>
          ))}
        </div>
        {status && <div className="status-indicator">{status}</div>}
        <div className="workspace-summary">
          <span className="summary-chip"><strong>Session:</strong> {session || "None"}</span>
          <span className="summary-chip"><strong>Selected Sources:</strong> {selectedPdfs.length}</span>
          <span className="summary-chip"><strong>Total Sources:</strong> {pdfs.length}</span>
          {mode !== "monitoring" && <span className="summary-chip"><strong>Mode:</strong> {mode.replace("_", " ").toUpperCase()}</span>}
        </div>

        {mode !== "monitoring" && (
          <div className="global-highlight-search">
            <form className="input-group" onSubmit={searchMyHighlights}>
              <input
                type="text"
                value={highlightSearch}
                onChange={(e) => setHighlightSearch(e.target.value)}
                placeholder='Search in my highlights (e.g. "supporting evidence for claim X")'
              />
              <button className="btn-icon" type="submit">Go</button>
            </form>
            {highlightSearchLoading && <p className="muted">Searching highlights...</p>}
            {highlightSearchResults.length > 0 && (
              <div className="global-highlight-results">
                {highlightSearchResults.slice(0, 5).map((hl) => (
                  <button
                    key={`global-${hl.id}-${hl.score}`}
                    className="highlight-search-hit"
                    onClick={() =>
                      openCitationViewer({
                        source: hl.filename,
                        page: hl.page || 1,
                        snippet: hl.text,
                        pageOneIndexed: true,
                      })
                    }
                  >
                    <strong>{hl.filename}</strong> p.{hl.page} ({(hl.score || 0).toFixed(3)})
                    <p>{hl.text}</p>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="chat-container">
          {mode === 'monitoring' ? (
            <div className="monitoring-dashboard">
              <h2>System Monitoring</h2>
              {metrics ? (
                <div className="metrics-grid">
                  <div className="metric-card">
                    <h3>Average Latency</h3>
                    <p className="metric-value">{metrics.queries.latency_avg_ms}ms</p>
                  </div>
                  <div className="metric-card">
                    <h3>Total Queries</h3>
                    <p className="metric-value">{metrics.queries.total}</p>
                  </div>
                  <div className="metric-card">
                    <h3>Error Rate</h3>
                    <p className="metric-value">{(metrics.errors.rate * 100).toFixed(1)}%</p>
                  </div>
                  <div className="metric-card">
                    <h3>Active Sessions</h3>
                    <p className="metric-value">{metrics.sessions?.active_count ?? 0}</p>
                  </div>
                  <div className="metric-info-full">
                    <h4>Queries by Mode</h4>
                    <ul>
                      {Object.entries(metrics.queries.by_mode || {}).map(([m, count]) => (
                        <li key={m}><strong>{m.toUpperCase()}:</strong> {count}</li>
                      ))}
                    </ul>
                  </div>
                  {metrics.grounding && (
                    <>
                      <div className="metric-card">
                        <h3>Refusal Rate</h3>
                        <p className="metric-value">{(metrics.grounding.refusal_rate * 100).toFixed(1)}%</p>
                        <p className="metric-sub">{metrics.grounding.refusal_count} refusals</p>
                      </div>
                      <div className="metric-card">
                        <h3>Low Evidence Rate</h3>
                        <p className="metric-value">{(metrics.grounding.insufficient_evidence_rate * 100).toFixed(1)}%</p>
                        <p className="metric-sub">{metrics.grounding.insufficient_evidence_count} flagged</p>
                      </div>
                      <div className="metric-card">
                        <h3>Avg Chunks Retrieved</h3>
                        <p className="metric-value">{metrics.grounding.avg_retrieved_chunks}</p>
                      </div>
                      <div className="metric-card">
                        <h3>Avg Confidence</h3>
                        <p className="metric-value">{(metrics.grounding.avg_confidence_score || 0).toFixed(3)}</p>
                      </div>
                    </>
                  )}
                </div>
              ) : <p>Loading metrics...</p>}
            </div>
          ) : messages.length === 0 ? (
            <div className="welcome-screen">
              <h2>Welcome to your research workspace</h2>
              <p>Upload scientific papers, select them as context, and ask questions with strict citation grounding.</p>
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={i} className={`message ${msg.role}`}>
                <div className="message-content">
                  {msg.title && <h3 className="lit-review-title">{msg.title}</h3>}

                  {msg.comparison ? (
                    <div className="comparison-view">
                      <h4>{msg.text}</h4>
                      {msg.comparison.message && (
                        <p className="muted" style={{ marginBottom: "12px" }}>
                          {msg.comparison.message}
                        </p>
                      )}
                      {msg.comparison.claims?.map((c, idx) => (
                        <div key={idx} className="claim-card">
                          <p className="claim-text"><strong>Claim:</strong> {c.claim}</p>
                          <div className="papers-stances">
                            {c.papers?.map((p, pidx) => (
                              <div key={pidx} className={`stance-badge ${p.stance}`}>
                                <span>{p.paper_id.split('_').pop()}</span>: {p.stance}
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="formatted-text">
                      {msg.text.split('\n').map((line, lidx) => (
                        <p key={lidx}>{line}</p>
                      ))}
                    </div>
                  )}

                  {msg.citations && msg.citations.length > 0 && (
                    <div className="citations-grid">
                      {msg.citations.map((c, j) => (
                        <button
                          key={j}
                          className={`citation-chip clickable ${j === 0 ? "top-evidence" : ""}`}
                          onClick={() => openCitationViewer(c)}
                          title={c.snippet || "Open citation in PDF viewer"}
                        >
                          View {c.source} (p.{Number(c.page || 0) + 1})
                          {typeof c.score === "number" && (
                            <span className="citation-score">{c.score.toFixed(3)}</span>
                          )}
                          {j === 0 && <span className="citation-best">Best</span>}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
          <div ref={chatEndRef} />
        </div>

        {pdfViewer && (
          <div className={`pdf-drawer ${isPdfDrawerFullscreen ? "fullscreen" : ""}`}>
            <div className="pdf-drawer-header">
              <div>
                <strong>{pdfViewer.filename}</strong>
                <p>Page {pdfViewer.page}</p>
              </div>
              <div className="pdf-drawer-actions">
                <button
                  className="text-btn"
                  onClick={() => setIsPdfDrawerFullscreen((v) => !v)}
                >
                  {isPdfDrawerFullscreen ? "Windowed" : "Fullscreen"}
                </button>
                <button
                  className="text-btn"
                  onClick={() => {
                    setPdfViewer(null);
                    setIsPdfDrawerFullscreen(false);
                  }}
                >
                  Close
                </button>
              </div>
            </div>

            {pdfViewer.mode === "pdf" ? (
              <iframe
                title="PDF.js Viewer"
                className="pdf-frame"
                src={pdfViewer.viewerUrl}
              />
            ) : (
              <div className="text-preview-panel">
                <div className="text-preview-header">
                  <strong>Text Preview</strong>
                  <span className="muted">Metadata-only source</span>
                </div>
                <pre className="text-preview-content">
                  {pdfViewer.textPreview || pdfViewer.snippet || "No preview text available."}
                </pre>
              </div>
            )}

            <div className="drawer-section">
              <h4>Citation Snippet</h4>
              <p className="snippet-box">{pdfViewer.snippet || "No snippet provided."}</p>
              {pdfViewer.precisePhrase && (
                <p className="muted" style={{ marginTop: "6px" }}>
                  Precise page phrase: "{pdfViewer.precisePhrase}"
                </p>
              )}
            </div>

            <div className="drawer-section">
              <h4>Create Highlight</h4>
              <input
                type="text"
                value={highlightNote}
                onChange={(e) => setHighlightNote(e.target.value)}
                placeholder="Optional note..."
              />
              <input
                type="text"
                value={highlightTags}
                onChange={(e) => setHighlightTags(e.target.value)}
                placeholder="Tags (comma-separated)"
              />
              <button className="btn-primary" onClick={createHighlightFromCitation}>
                Save Highlight
              </button>
            </div>

            <div className="drawer-section">
              <h4>Highlights In This Document</h4>
              <div className="highlight-list">
                {highlights.map((hl) => (
                  <div key={hl.id} className="highlight-item">
                    <div className="highlight-row">
                      <span>p.{hl.page}</span>
                      <button className="text-btn" onClick={() => deleteHighlight(hl.id)}>
                        Delete
                      </button>
                    </div>
                    <p>{hl.text}</p>
                    {hl.note && <p className="muted">Note: {hl.note}</p>}
                  </div>
                ))}
                {highlights.length === 0 && <p className="muted">No highlights yet.</p>}
              </div>
            </div>

            <div className="drawer-section">
              <h4>Search In My Highlights (Session)</h4>
              <form className="input-group" onSubmit={searchMyHighlights}>
                <input
                  type="text"
                  value={highlightSearch}
                  onChange={(e) => setHighlightSearch(e.target.value)}
                  placeholder='e.g. supporting evidence for "claim X"'
                />
                <button className="btn-icon" type="submit">Go</button>
              </form>
              {highlightSearchLoading && <p className="muted">Searching highlights...</p>}
              <div className="highlight-list">
                {highlightSearchResults.map((hl) => (
                  <button
                    key={`${hl.id}-${hl.score}`}
                    className="highlight-search-hit"
                    onClick={() =>
                      openCitationViewer({
                        source: hl.filename,
                        page: hl.page || 1,
                        snippet: hl.text,
                        pageOneIndexed: true,
                      })
                    }
                  >
                    <strong>{hl.filename}</strong> p.{hl.page} ({(hl.score || 0).toFixed(3)})
                    <p>{hl.text}</p>
                  </button>
                ))}
                {highlightSearchResults.length === 0 && <p className="muted">No search results yet.</p>}
              </div>
            </div>
          </div>
        )}

        {mode !== 'monitoring' && (
          <div className="input-area">
            <form onSubmit={askQuestion} className="chat-input-wrapper">
              <input
                type="text"
                placeholder={selectedPdfs.length > 0 ? `Ask a question in ${mode.replace('_', ' ').toUpperCase()} mode...` : "Select a source to start asking questions"}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                disabled={loading}
              />
              <button
                type="submit"
                className="btn-icon"
                disabled={loading || !question.trim()}
              >
                Send
              </button>
            </form>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;

