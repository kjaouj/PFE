import { useState, useEffect, useRef } from "react";
import "./App.css";

function App() {
  const [session, setSession] = useState("Research Session");
  const [sessions, setSessions] = useState([]);
  const [newSessionName, setNewSessionName] = useState("");
  const [isSessionsOpen, setIsSessionsOpen] = useState(true);
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
  const fileInputRef = useRef(null);
  const chatEndRef = useRef(null);

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

  const loadSessions = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/sessions/");
      if (res.ok) {
        const data = await res.json();
        setSessions(data);
      }
    } catch (err) {
      console.error("Failed to load sessions", err);
    }
  };

  const loadHistory = async () => {
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/api/history/?session=${encodeURIComponent(session)}`
      );
      if (res.ok) {
        const data = await res.json();
        setMessages(data.history || []);
      }
    } catch (err) {
      console.error("Failed to load history", err);
    }
  };

  const loadPdfs = async () => {
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/api/pdfs/?session=${encodeURIComponent(session)}`
      );
      if (res.ok) {
        const data = await res.json();
        setPdfs(data.pdfs || []);
      }
    } catch (err) {
      console.error("Failed to load PDFs", err);
    }
  };

  const loadMetrics = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/metrics/summary/");
      if (res.ok) {
        const data = await res.json();
        setMetrics(data);
      }
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

  const openCitationViewer = async (citation) => {
    const filename = citation.source;
    const page = citation.pageOneIndexed
      ? Number(citation.page || 1)
      : Number(citation.page || 0) + 1;
    const snippet = (citation.snippet || "").trim();
    const docUrl = `http://127.0.0.1:8000/media/pdfs/${encodeURIComponent(filename)}`;

    let precisePhrase = "";
    const doc = pdfs.find((p) => p.filename === filename);
    if (doc) {
      try {
        const res = await fetch(
          `http://127.0.0.1:8000/api/documents/${doc.id}/page-text/?page=${page}`
        );
        if (res.ok) {
          const payload = await res.json();
          precisePhrase = choosePrecisePhrase(snippet, payload.text || "");
        }
      } catch (err) {
        console.error("Failed fetching page text for precise highlight", err);
      }
    }

    const exactSearch = precisePhrase ? `"${precisePhrase}"` : "";
    const viewerUrl = `https://mozilla.github.io/pdf.js/web/viewer.html?file=${encodeURIComponent(docUrl)}#page=${page}${exactSearch ? `&search=${encodeURIComponent(exactSearch)}&phrase=true` : ""}`;

    setPdfViewer({
      filename,
      page,
      snippet,
      viewerUrl,
      precisePhrase,
    });
  };

  const loadHighlightsForDocument = async (filename) => {
    const doc = pdfs.find((p) => p.filename === filename);
    if (!doc) return setHighlights([]);

    try {
      const res = await fetch(`http://127.0.0.1:8000/api/highlights/?document_id=${doc.id}`);
      const data = await res.json();
      if (res.ok) setHighlights(data.highlights || []);
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
      const res = await fetch("http://127.0.0.1:8000/api/highlights/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: doc.id,
          page: pdfViewer.page,
          start_offset: 0,
          end_offset: pdfViewer.snippet.length,
          text: pdfViewer.snippet,
          note: highlightNote,
          tags,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setHighlightNote("");
        setHighlightTags("");
        await loadHighlightsForDocument(pdfViewer.filename);
        setStatus("Highlight saved");
      } else {
        setStatus(data.error || "Failed to save highlight");
      }
    } catch (err) {
      setStatus("Failed to save highlight");
    }
  };

  const deleteHighlight = async (highlightId) => {
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/highlights/${highlightId}/`, {
        method: "DELETE",
      });
      if (res.ok && pdfViewer?.filename) {
        await loadHighlightsForDocument(pdfViewer.filename);
      }
    } catch (err) {
      console.error("Failed to delete highlight", err);
    }
  };

  const searchMyHighlights = async (e) => {
    e?.preventDefault();
    if (!highlightSearch.trim() || !session) return;

    try {
      const res = await fetch(
        `http://127.0.0.1:8000/api/highlights/search/?session=${encodeURIComponent(session)}&q=${encodeURIComponent(highlightSearch)}`
      );
      const data = await res.json();
      if (res.ok) {
        setHighlightSearchResults(data.results || []);
      }
    } catch (err) {
      console.error("Highlight search failed", err);
    }
  };

  const handleCreateSession = async (e) => {
    e?.preventDefault();
    if (!newSessionName.trim()) return;

    setStatus("Creating session...");
    try {
      const res = await fetch("http://127.0.0.1:8000/api/session/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newSessionName }),
      });
      if (res.ok) {
        setSession(newSessionName);
        setNewSessionName("");
        await loadSessions();
        setStatus("Session ready");
      }
    } catch (err) {
      setStatus("Error creating session");
    }
  };

  const deleteSession = async (e, name) => {
    e.stopPropagation();
    if (!window.confirm(`Delete entire workflow for "${name}"? This cannot be undone.`)) return;

    setStatus("Deleting session data...");
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/session/${encodeURIComponent(name)}/`, {
        method: "DELETE",
      });
      if (res.ok) {
        if (session === name) {
          setSession("");
          setPdfs([]);
          setMessages([]);
        }
        await loadSessions();
        setStatus("Session deleted");
      }
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
      const response = await fetch("http://127.0.0.1:8000/api/upload/", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      setStatus(data.message || "Upload initiated");
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
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/search/external/?q=${encodeURIComponent(arxivQuery)}&source=${searchSource}`);
      const data = await res.json();
      if (res.ok) {
        setArxivResults(data.results || []);
        setStatus(data.results?.length > 0 ? "Search complete" : "No results found");
      } else {
        if (res.status === 429) {
          setStatus(`${searchSource.toUpperCase()}: Too many requests. Please wait.`);
        } else {
          setStatus("Search Error: " + (data.error || "Unknown"));
        }
      }
    } catch (err) {
      setStatus("External search failed");
    }
  };

  const importExternal = async (id) => {
    setStatus(`Importing from ${searchSource.toUpperCase()}...`);
    try {
      const res = await fetch("http://127.0.0.1:8000/api/import/external/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, source: searchSource, session }),
      });
      const data = await res.json();
      if (res.ok) {
        setStatus("Import initiated");
        loadPdfs();
      } else {
        setStatus("Import failed: " + (data.error || "Unknown"));
      }
    } catch (err) {
      setStatus("Import failed");
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
      const response = await fetch("http://127.0.0.1:8000/api/ask/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: question,
          sources: selectedPdfs,
          session,
          mode: mode
        }),
      });

      const data = await response.json();
      if (response.ok) {
        if (mode === "compare") {
          setMessages(prev => [...prev, {
            role: "assistant",
            text: `Comparison for: "${question}"`,
            comparison: data
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
      } else {
        throw new Error(data.error || "Backend error");
      }
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
      const res = await fetch("http://127.0.0.1:8000/api/delete/", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session, filename }),
      });
      if (res.ok) {
        loadPdfs();
        setSelectedPdfs(prev => prev.filter(p => p !== filename));
      }
    } catch (err) {
      console.error("Delete failed", err);
    }
  };

  return (
    <div className={`app-layout ${theme === 'light' ? 'light-mode' : ''}`}>
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div style={{ display: 'flex', alignItems: 'center', width: '100%' }}>
            <h1>Scientific Navigator</h1>
            <button
              className="theme-toggle"
              onClick={toggleTheme}
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            >
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
          </div>
        </div>

        <div className="sidebar-scroll">
          <div className="session-config">
            <span className="section-label" onClick={() => setIsSessionsOpen(!isSessionsOpen)}>
              Your Sessions
              <span className={`toggle-icon ${isSessionsOpen ? 'open' : ''}`}>▶</span>
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
                    <span className="session-item-icon">📁</span>
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
                  {['arxiv', 'pubmed', 'semanticscholar', 'acl', 'medrxiv'].map(src => (
                    <button
                      key={src}
                      className={`source-tab ${searchSource === src ? 'active' : ''}`}
                      onClick={() => {
                        setSearchSource(src);
                        setArxivResults([]);
                      }}
                    >
                      {src === 'semanticscholar' ? 'Scholar' : (src === 'medrxiv' ? 'medRxiv' : src.toUpperCase())}
                    </button>
                  ))}

                </div>
                <form className="input-group" onSubmit={searchExternal}>
                  <input
                    type="text"
                    value={arxivQuery}
                    onChange={(e) => setArxivQuery(e.target.value)}
                    placeholder={`Search ${searchSource}...`}
                  />
                  <button type="submit" className="btn-icon" disabled={loading}>🔍</button>
                </form>
                <div className="arxiv-results">
                  {arxivResults.map((res, i) => (
                    <div key={i} className={`arxiv-result-item ${previewId === res.id ? 'expanded' : ''}`}>
                      <div className="arxiv-res-header" onClick={() => setPreviewId(previewId === res.id ? null : res.id)}>
                        <p className="arxiv-res-title">{res.title}</p>
                        <span className="expand-chevron">{previewId === res.id ? '▼' : '▶'}</span>
                      </div>

                      {previewId === res.id && (
                        <div className="arxiv-res-preview">
                          <p className="arxiv-meta"><strong>Authors:</strong> {res.authors?.join(', ')}</p>
                          <p className="arxiv-meta"><strong>Link:</strong> {res.date}</p>
                          <div className="arxiv-abstract-container">
                            <strong>Abstract:</strong>
                            <p className="arxiv-abstract">{res.abstract}</p>
                          </div>
                          <div className="arxiv-actions">
                            <a
                              href={res.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="arxiv-link-btn"
                              onClick={(e) => e.stopPropagation()}
                            >
                              Explore ↗
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
                        {pdf.filename} • <span className={`status-badge ${(pdf.error_message?.includes('Summary-only') ? 'summary' : (pdf.status || 'INDEXED').toLowerCase())}`}>
                          {pdf.error_message?.includes('Summary-only') ? 'SUMMARY' : (pdf.status || 'INDEXED')}
                        </span>
                      </span>
                    </div>
                    <button
                      className="delete-source-btn"
                      onClick={(e) => deletePdf(e, pdf.filename)}
                    >
                      &times;
                    </button>
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
      </aside>

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
                          className="citation-chip clickable"
                          onClick={() => openCitationViewer(c)}
                          title={c.snippet || "Open citation in PDF viewer"}
                        >
                          View {c.source} (p.{Number(c.page || 0) + 1})
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
          <div className="pdf-drawer">
            <div className="pdf-drawer-header">
              <div>
                <strong>{pdfViewer.filename}</strong>
                <p>Page {pdfViewer.page}</p>
              </div>
              <button
                className="text-btn"
                onClick={() => setPdfViewer(null)}
              >
                Close
              </button>
            </div>

            <iframe
              title="PDF.js Viewer"
              className="pdf-frame"
              src={pdfViewer.viewerUrl}
            />

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
                ➔
              </button>
            </form>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;

