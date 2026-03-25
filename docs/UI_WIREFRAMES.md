# Trade Journal — UI Wireframe Specification

**Reference document for the Streamlit dark-theme interface.**

---

## Global theme

```
Background:       #0d1117
Card background:  #161b22
Input background: #1c2129
Hover:            #1f2937
Border:           #30363d
Text primary:     #e6edf3
Text secondary:   #8b949e
Text muted:       #6e7681
Green (win/long): #3fb950
Red (loss/short): #f85149
Blue (info/stock):#58a6ff
Amber (spread):   #d29922
Purple (option):  #bc8cff
Teal (account):   #3ddbd9
Font:             'SF Mono', 'Fira Code', 'Cascadia Code', monospace
```

## Navigation

5 tabs as horizontal buttons at top:
- Needs review (default active)
- Trade detail
- History
- Statistics
- Settings

Active tab: blue background (#58a6ff), white text.
Inactive tab: transparent, secondary text (#8b949e).

---

## Screen 1: Needs review

### Layout (top to bottom)

1. **Summary metrics row** (4 cards, equal width)
   - Awaiting review: count in blue
   - Today's imports: count
   - Today's P&L: green/red
   - Last import: timestamp

2. **Filter bar** (3 dropdowns inline)
   - Account: All accounts / [detected accounts]
   - Type: All types / Stock / Single option / Spread
   - Setup type: All setup types / [user setup types]

3. **Trade table** (11 columns)
   | Acct | Symbol | Type | Setup | Dir | Entry | Exit | P&L | Class | Status | Expand |
   
   - Acct: teal badge with account alias
   - Symbol: bold white text
   - Type: colored badge (blue=stock, purple=single opt, amber=spread)
   - Setup: muted text, freeform
   - Dir: green badge=Long/Debit, red badge=Short/Credit
   - Entry/Exit: price text
   - P&L: green (+) or red (-)
   - Class: A+/A/B/C/F or dash if unreviewed
   - Status: blue badge "Review" or green badge "Done"
   - Expand: arrow button (▶)

4. **Expanded row** (revealed on click)
   - TradingView chart embed area (dark background, centered)
   - Entry/exit labels: green dot + entry price/time, red dot + exit price/time
   - "Open review" button (blue, links to Trade Detail tab)

---

## Screen 2: Trade detail

### Layout (top to bottom)

1. **Trade header**
   - Left: Symbol + description (e.g., "TSLA 250/260C — Call debit spread")
   - Right: Account tag, type badge, direction badge, status badge

2. **Facts grid** (4 columns × 3 rows = 12 boxes)
   Each box: dark input background, muted label on top, bold value below.
   - Entry, Exit, Quantity/Contracts, Spread width
   - Max profit, Max loss, Gross P&L, Net P&L
   - Holding time, DTE at entry, Breakeven, Fees

3. **Legs table** (only for spreads)
   | Leg | Type | Side | Strike | Expiry | Open | Close |

4. **TradingView chart card**
   - Widget embed area
   - Entry/exit text labels below (centered)

5. **Manual review card**
   Three sub-tabs:

   **Notes tab:**
   - Setup class: 5 pill buttons (A+/A/B/C/F), single select
   - Setup type: dropdown from setup_types table
   - Tags: text input (comma-separated)
   - Comment: textarea
   - QQQ EMA note: text input
   - Symbol EMA note: text input
   - TQ/TICKQ note: text input

   **Mental state tab:**
   - Emotion: 5 pill buttons (Calm/Focused/FOMO/Fearful/Impatient), multi-select
   - Confidence rating: 5 pill buttons (1-5), single select
   - Market regime note: text input

   **Outcome tab:**
   - Execution score: 5 pill buttons (1-5), single select
   - Would take again: 3 pill buttons (Yes/No/With changes), single select
   - Lesson learned: textarea
   - Mistake narrative: textarea

   **Save review** button (blue, right-aligned)

---

## Screen 3: History

### Layout

1. **Filter bar** (2 rows × 4 columns)
   Row 1: Account, Date from, Date to, Type
   Row 2: Setup type, Status, P&L, Symbol text input

2. **Trade table**
   | Date | Acct | Symbol | Type | Setup | Dir | P&L | Class | Status |

---

## Screen 4: Statistics

### Layout

1. **Metrics row 1** (4 cards)
   - Total trades, Win rate (green), Avg winner (green), Avg loser (red)

2. **Metrics row 2** (4 cards)
   - Net P&L (green/red), Profit factor (blue), Best trade (green), Worst trade (red)

3. **Breakdown tables** (2×2 grid)
   - By trade type: Type / Trades / Win% / Net P&L
   - By setup type: Setup / Trades / Win% / Net P&L
   - By setup class: Class / Trades / Win% / Net P&L
   - By manual tag: Tag / Trades / Win% / Net P&L

4. **Cumulative P&L chart** (planned, not yet built)
   - Line chart, x=date, y=cumulative net P&L
   - Respects account filter

---

## Screen 5: Settings

### Layout (stacked cards)

1. **IBKR connection card**
   - Flex token (password input)
   - Query ID (text input)
   - Save button (blue)

2. **Import controls** (inline buttons)
   - Run import now
   - Upload XML file

3. **Accounts card**
   - Auto-detected accounts listed
   - Editable alias field per account

4. **Setup types card**
   - Current types shown as blue badges
   - "New setup type" text input + "+ Add" button

5. **TQ/TICKQ card**
   - Enable/disable toggle
   - Yahoo symbol text input

6. **Backup & export card** (inline buttons)
   - Backup database
   - Export CSV
   - Export SQLite

7. **Import history table**
   | Date | Status | Fills | Trades | Filename |

---

## Badge color reference

| Badge type | Background | Text color |
|------------|-----------|------------|
| Stock | rgba(88,166,255,.15) | #58a6ff |
| Single opt | rgba(188,140,255,.15) | #bc8cff |
| Spread | rgba(210,153,34,.15) | #d29922 |
| Long/Debit | rgba(63,185,80,.15) | #3fb950 |
| Short/Credit | rgba(248,81,73,.15) | #f85149 |
| Needs review | rgba(88,166,255,.15) | #58a6ff |
| Done/Reviewed | rgba(63,185,80,.1) | #3fb950 |
| Account tag | rgba(61,219,217,.12) | #3ddbd9 |
