import React, { useState, useEffect, useRef } from 'react';

// Credentials Configuration
const VALID_USERNAME = 'admin';
const VALID_PASSWORD = 'aisteel2026';

// Google Sheets CSV Export URL
const SPREADSHEET_CSV_URL = 'https://docs.google.com/spreadsheets/d/19C4vdoFIlMQGhAyUmYjaoSatU-jQPy4BJIpoXbMZkEM/gviz/tq?tqx=out:csv&sheet=AllData';

// Custom CSV Parser supporting quotes and line breaks
function parseCSV(csvText) {
  const lines = [];
  let currentLine = [];
  let insideQuote = false;
  let currentValue = '';
  
  for (let i = 0; i < csvText.length; i++) {
    const char = csvText[i];
    const nextChar = csvText[i+1];
    
    if (char === '"') {
      if (insideQuote && nextChar === '"') {
        currentValue += '"';
        i++;
      } else {
        insideQuote = !insideQuote;
      }
    } else if (char === ',' && !insideQuote) {
      currentLine.push(currentValue);
      currentValue = '';
    } else if ((char === '\n' || char === '\r') && !insideQuote) {
      if (char === '\r' && nextChar === '\n') {
        i++;
      }
      currentLine.push(currentValue);
      lines.push(currentLine);
      currentLine = [];
      currentValue = '';
    } else {
      currentValue += char;
    }
  }
  if (currentValue || currentLine.length > 0) {
    currentLine.push(currentValue);
    lines.push(currentLine);
  }
  return lines;
}

// Terminology Keyword Highlighter
function highlightKeywords(text) {
  if (!text) return '';
  const keywords = [
    /AiSteel/gi,
    /تیرآهن/g,
    /تیر آهن/g,
    /میلگرد/g,
    /میل گرد/g,
    /آهن‌آلات/g,
    /آهن آلات/g,
    /نبشی/g,
    /پروفیل/g,
    /لوله/g,
    /ریخته‌گری/g,
    /ریخته گری/g,
    /خرید فولاد/g
  ];
  
  let highlighted = text;
  keywords.forEach(keyword => {
    highlighted = highlighted.replace(keyword, (match) => {
      return `<span class="highlight-tag">${match}</span>`;
    });
  });
  
  return highlighted;
}

// ─────────────────────────────────────────────────────────────
// General-purpose meaningless message filter
// Rules are structural/pattern-based — NOT content-specific
// ─────────────────────────────────────────────────────────────
function isMeaninglessMessage(content) {
  if (!content) return true;

  // Normalize: strip directional marks, collapse whitespace
  const norm = content
    .trim()
    .replace(/[\u200e\u200f\u200b\u200c\u200d]/g, '')
    .replace(/[\s\u00a0\u202f\t\r\n]+/g, ' ')
    .trim();

  if (!norm) return true;

  const lower = norm.toLowerCase();

  // ── Rule 1: Too short to carry real meaning ──────────────────
  // Strip all spaces, punctuation, numbers → if real chars < 4, skip
  const meaningful = norm.replace(/[\s\d\p{P}؟،؛!?.,;:\-_@#$%^&*()+=<>]/gu, '');
  if (meaningful.length < 4) return true;

  // ── Rule 2: Entire message is a single URL ───────────────────
  if (/^https?:\/\/\S+$/.test(lower)) return true;

  // ── Rule 3: Pattern — word/domain followed only by a number ──
  // Catches stats like: "SomeThing.com 55" or "Word 123"
  if (/^[\w][\w.\-]{1,40}\s+\d+$/.test(lower)) return true;

  // ── Rule 4: Short text ending with only question marks ───────
  // Catches "عرفان ؟؟" or "محمد خوشنودی ??" — name + no real question
  if (/^[^\d\n]{1,30}[؟?]{1,}$/.test(norm)) {
    // Allow through if it contains a sentence-level verb or conjunction
    const hasContext = /[،.!؟]{0,}\s*\w{4,}/.test(norm.slice(0, -2));
    if (!hasContext) return true;
  }

  // ── Rule 5: WhatsApp system action phrases ───────────────────
  // These are fixed WhatsApp-generated strings, not user content
  const systemPhrases = [
    'added you',
    'created this group',
    'joined using',
    "changed this group's",
    'changed the subject',
    'invited',
    'changed their phone number',
    'turned on messages',
    'waiting for this message',
    'changed the group description',
    'end-to-end encrypted',
    'this message was deleted',
    'you deleted this message',
  ];
  if (systemPhrases.some(p => lower.includes(p))) return true;

  // ── Rule 6: Media / file attachment placeholders ─────────────
  // Pattern: "[media type] omitted" or "<attached: ...>"
  if (/\b\w+\s+omitted\b/i.test(lower)) return true;
  if (/<attached:\s*[^>]*>/i.test(lower)) return true;
  // Persian equivalents: anything + "ضمیمه نشد" or "حذف شد"
  if (/ضمیمه نشد|حذف شد/.test(norm)) return true;

  return false;
}

export default function App() {
  // Theme Switching State
  const [theme, setTheme] = useState(localStorage.getItem('aisteel_theme') || 'dark');

  useEffect(() => {
    if (theme === 'light') {
      document.body.classList.add('light-theme');
    } else {
      document.body.classList.remove('light-theme');
    }
    localStorage.setItem('aisteel_theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  // Authentication State
  const [isAuthenticated, setIsAuthenticated] = useState(
    localStorage.getItem('aisteel_auth') === 'true'
  );
  const [user, setUser] = useState(localStorage.getItem('aisteel_user') || '');
  const [usernameInput, setUsernameInput] = useState('');
  const [passwordInput, setPasswordInput] = useState('');
  const [loginError, setLoginError] = useState('');

  // Dashboard Data State
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterSource, setFilterSource] = useState('all'); // 'all', 'text', 'voice'

  // Audio Player State
  const [activeAudioId, setActiveAudioId] = useState(null);
  const [audioProgress, setAudioProgress] = useState(0);
  const audioRef = useRef(null);

  // Fetch sheet data on authentication
  useEffect(() => {
    if (isAuthenticated) {
      fetchSheetData();
    }
  }, [isAuthenticated]);

  const fetchSheetData = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/records');
      if (!response.ok) throw new Error('خطا در بارگیری داده‌ها از وب‌سرویس داشبورد');
      
      const data = await response.json();
      
      if (data.error) {
        throw new Error(data.error);
      }
      
      // Map JSON properties to ensure all expected properties map perfectly
      const parsedRecords = data.map(item => {
        const mapped = {};
        Object.keys(item).forEach(key => {
          mapped[key] = item[key] !== null && item[key] !== undefined ? String(item[key]) : '';
        });
        return mapped;
      }).filter(item => (item.ID || item.Date) && !isMeaninglessMessage(item['Raw Content']));
      
      // Reverse chronological order (latest messages at top)
      parsedRecords.reverse();
      setRecords(parsedRecords);
      
    } catch (error) {
      console.error(error);
      alert('دریافت اطلاعات گوگل شیت ناموفق بود: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLogin = (e) => {
    e.preventDefault();
    if (usernameInput.trim().toLowerCase() === VALID_USERNAME && passwordInput === VALID_PASSWORD) {
      setIsAuthenticated(true);
      setUser(usernameInput);
      setLoginError('');
      localStorage.setItem('aisteel_auth', 'true');
      localStorage.setItem('aisteel_user', usernameInput);
    } else {
      setLoginError('نام کاربری یا رمز عبور اشتباه است!');
    }
  };

  const handleLogout = () => {
    setIsAuthenticated(false);
    setRecords([]);
    localStorage.removeItem('aisteel_auth');
    localStorage.removeItem('aisteel_user');
    stopAudio();
  };

  const stopAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setActiveAudioId(null);
    setAudioProgress(0);
  };

  const toggleAudio = (recordId, audioFileName) => {
    if (activeAudioId === recordId) {
      if (audioRef.current.paused) {
        audioRef.current.play();
      } else {
        audioRef.current.pause();
      }
      // Force React state update
      setActiveAudioId(recordId);
      return;
    }

    stopAudio();

    // Serve temp_audio folder contents served directly relative to the public URL
    const audioUrl = `temp_audio/${audioFileName}`;
    const audio = new Audio(audioUrl);
    audioRef.current = audio;
    setActiveAudioId(recordId);
    setAudioProgress(0);

    audio.play().catch(err => {
      alert(`فایل صوتی ${audioFileName} به صورت محلی در مسیر temp_audio قرار ندارد. برای شنیدن ویس، ویس‌ها را از پوشه فشرده شده در temp_audio اکسترکت کنید.`);
      stopAudio();
    });

    audio.addEventListener('timeupdate', () => {
      if (audio.duration) {
        setAudioProgress((audio.currentTime / audio.duration) * 100);
      }
    });

    audio.addEventListener('ended', () => {
      stopAudio();
    });
  };

  // 1. Calculate statistics
  const totalRecords = records.length;
  const voiceRecords = records.filter(r => r.Source === 'Voice');
  const successTranscripts = voiceRecords.filter(r => r['Transcription Status'] === 'Success').length;
  
  let totalDuration = 0;
  voiceRecords.forEach(r => {
    const d = parseFloat(r.Duration);
    if (!isNaN(d)) totalDuration += d;
  });

  // 2. Filter records based on active controls
  const filteredRecords = records.filter(r => {
    // Source Filter
    if (filterSource === 'text' && r.Source !== 'Text') return false;
    if (filterSource === 'voice' && r.Source !== 'Voice') return false;
    
    // Search Query Filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      const content = (r['Raw Content'] || '').toLowerCase();
      const sender = (r['Created By'] || '').toLowerCase();
      const transcript = (r['Transcript'] || '').toLowerCase();
      
      return content.includes(query) || sender.includes(query) || transcript.includes(query);
    }
    
    return true;
  });

  if (!isAuthenticated) {
    return (
      <div className="login-container">
        <button className="btn-icon theme-toggle-btn" onClick={toggleTheme} style={{ position: 'absolute', top: '16px', right: '16px', zIndex: 10 }} title={theme === 'dark' ? 'پوسته روشن' : 'پوسته تاریک'}>
          <i className={`fas ${theme === 'dark' ? 'fa-sun' : 'fa-moon'}`}></i>
        </button>
        <div className="login-card glass-panel">
          <div className="login-logo-container">
            <img src={logoUrl} alt="AiSteel Logo" className="login-logo" />
          </div>
          <div className="login-header">
            <h2>خوش آمدید</h2>
            <p>داشبورد یکپارچه نظارت و آنالیز داده‌های AiSteel (React + Vite)</p>
          </div>
          
          {loginError && (
            <div className="error-message">
              <i className="fas fa-exclamation-triangle"></i>
              <span>{loginError}</span>
            </div>
          )}
          
          <form onSubmit={handleLogin}>
            <div className="form-group">
              <label className="form-label" htmlFor="username">نام کاربری</label>
              <div className="input-wrapper">
                <input
                  className="form-input"
                  type="text"
                  id="username"
                  placeholder="نام کاربری خود را وارد کنید"
                  required
                  value={usernameInput}
                  onChange={(e) => setUsernameInput(e.target.value)}
                  autoComplete="username"
                />
                <i className="fas fa-user input-icon"></i>
              </div>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="password">رمز عبور</label>
              <div className="input-wrapper">
                <input
                  className="form-input"
                  type="password"
                  id="password"
                  placeholder="••••••••"
                  required
                  value={passwordInput}
                  onChange={(e) => setPasswordInput(e.target.value)}
                  autoComplete="current-password"
                />
                <i className="fas fa-lock input-icon"></i>
              </div>
            </div>
            <button class="btn-primary" type="submit">
              <span>ورود به پنل مدیریت</span>
              <i class="fas fa-arrow-left"></i>
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-container">
      {/* Navigation Header */}
      <nav className="navbar glass-panel">
        <div className="navbar-actions">
          <button className="btn-icon" onClick={handleLogout} title="خروج از حساب">
            <i className="fas fa-sign-out-alt"></i>
          </button>
          <button className="btn-icon theme-toggle-btn" onClick={toggleTheme} title={theme === 'dark' ? 'پوسته روشن' : 'پوسته تاریک'}>
            <i className={`fas ${theme === 'dark' ? 'fa-sun' : 'fa-moon'}`}></i>
          </button>
          <span className="sender-name">کاربر: {user}</span>
        </div>
        <div className="navbar-brand">
          <span className="text-gradient-steel" style={{ fontFamily: 'var(--font-outfit)', fontWeight: 800, fontSize: '20px' }}>AiSteel Dashboard</span>
          <img src={logoUrl} alt="AiSteel Logo" className="navbar-logo" />
        </div>
      </nav>

      <main className="main-content">
        {/* Statistics Cards */}
        <section className="stats-grid">
          <div className="stat-card glass-panel">
            <div className="stat-icon total"><i className="fas fa-envelope"></i></div>
            <div className="stat-info">
              <h3>کل پیام‌های چت</h3>
              <div className="stat-number">{totalRecords}</div>
            </div>
          </div>
          <div className="stat-card glass-panel">
            <div className="stat-icon audio"><i class="fas fa-microphone"></i></div>
            <div className="stat-info">
              <h3>فایل‌های صوتی</h3>
              <div className="stat-number">{voiceRecords.length}</div>
            </div>
          </div>
          <div className="stat-card glass-panel">
            <div className="stat-icon success"><i className="fas fa-check-circle"></i></div>
            <div className="stat-info">
              <h3>متنی‌سازی موفق</h3>
              <div className="stat-number">{voiceRecords.length > 0 ? Math.round((successTranscripts / voiceRecords.length) * 100) : 0}%</div>
            </div>
          </div>
          <div className="stat-card glass-panel">
            <div className="stat-icon duration"><i className="fas fa-clock"></i></div>
            <div className="stat-info">
              <h3>کل زمان مکالمات</h3>
              <div className="stat-number">{Math.round(totalDuration)} ثانیه</div>
            </div>
          </div>
        </section>

        {/* Search & Filters Control Bar */}
        <section className="control-bar glass-panel">
          <div className="filter-actions">
            <button
              className={`filter-btn ${filterSource === 'all' ? 'active' : ''}`}
              onClick={() => setFilterSource('all')}
            >
              <span>همه پیام‌ها</span>
            </button>
            <button
              className={`filter-btn ${filterSource === 'text' ? 'active' : ''}`}
              onClick={() => setFilterSource('text')}
            >
              <i className="fas fa-align-right"></i>
              <span>متن خام</span>
            </button>
            <button
              className={`filter-btn ${filterSource === 'voice' ? 'active' : ''}`}
              onClick={() => setFilterSource('voice')}
            >
              <i className="fas fa-microphone"></i>
              <span>صداها</span>
            </button>
          </div>
          <div className="search-box">
            <input
              className="search-input"
              type="text"
              placeholder="جستجو در پیام‌ها، ترنسکریپت‌ها یا فرستنده‌ها..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <i className="fas fa-search search-icon"></i>
          </div>
        </section>

        {/* Loading State / Record Grid */}
        {loading ? (
          <div className="loading-box glass-panel">
            <div className="spinner"></div>
            <p>درحال واکشی و آنالیز اطلاعات گوگل شیت...</p>
          </div>
        ) : (
          <section className="grid-container">
            {filteredRecords.length === 0 ? (
              <div className="loading-box glass-panel">
                <i className="fas fa-folder-open" style={{ fontSize: '40px', color: '#8b949e', marginBottom: '12px' }}></i>
                <p>هیچ پیامی با فیلترها و جستجوی شما مطابقت ندارد.</p>
              </div>
            ) : (
              filteredRecords.map(r => {
                const isVoice = r.Source === 'Voice';
                const sender = r['Created By'] || 'کاربر';
                const initials = sender.substring(0, 1).toUpperCase();
                const isPlaying = activeAudioId === r.ID && audioRef.current && !audioRef.current.paused;

                return (
                  <article key={r.ID || Math.random()} className="record-card glass-panel">
                    <div className="card-header">
                      <div className="meta-info">
                        <span className={`source-badge ${isVoice ? 'voice' : 'text'}`}>{isVoice ? 'پیام صوتی' : 'پیام متنی'}</span>
                        <span><i className="far fa-calendar-alt"></i> {r.Date}</span>
                        <span><i className="far fa-clock"></i> {r.Time}</span>
                      </div>
                      <div className="sender-badge">
                        <span className="sender-name">{sender}</span>
                        <span className="sender-avatar">{initials}</span>
                      </div>
                    </div>
                    
                    <div className="card-body" dangerouslySetInnerHTML={{ __html: highlightKeywords(r['Raw Content']) }}></div>
                    
                    {isVoice && r['Audio File'] && (
                      <>
                        <div className="audio-player-box">
                          <span className="audio-duration">{r.Duration} ثانیه</span>
                          <div className="audio-track-info">
                            <span className="audio-file-name">{r['Audio File']}</span>
                            <div className="audio-waveform-fallback">
                              <div
                                className={`audio-waveform-progress progress-${r.ID}`}
                                style={{ width: activeAudioId === r.ID ? `${audioProgress}%` : '0%' }}
                              ></div>
                            </div>
                          </div>
                          <button className="play-btn" onClick={() => toggleAudio(r.ID, r['Audio File'])}>
                            <i className={`fas ${isPlaying ? 'fa-pause' : 'fa-play'}`}></i>
                          </button>
                        </div>
                        
                        {r['Transcription Status'] === 'Success' && r['Transcript'] && (
                          <div className="card-body" style={{ marginTop: '12px', fontSize: '13px', color: '#8b949e', borderTop: '1px dashed var(--border-metal)', paddingTop: '10px' }}>
                            <strong><i className="fas fa-quote-right" style={{ fontSize: '10px', marginLeft: '4px' }}></i> متن ترنسکریپت خام:</strong><br />
                            <div dangerouslySetInnerHTML={{ __html: highlightKeywords(r['Transcript']) }}></div>
                          </div>
                        )}
                        
                        {r['Transcription Status'] !== 'Success' && r['Transcription Status'] !== 'N/A' && (
                          <div className="error-message" style={{ marginTop: '12px', marginBottom: 0, padding: '6px 12px', fontSize: '12px' }}>
                            <i className="fas fa-exclamation-triangle"></i>
                            <span>متنی‌سازی ناموفق: {r['Transcription Status']}</span>
                          </div>
                        )}
                      </>
                    )}
                  </article>
                );
              })
            )}
          </section>
        )}
      </main>
    </div>
  );
}
