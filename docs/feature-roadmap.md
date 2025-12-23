# Feature Roadmap

A prioritized list of potential features and improvements for Acclaimed Games.

## Priority Levels
- **P0 - Critical**: Essential for core user experience
- **P1 - High**: Significant value, should be done soon
- **P2 - Medium**: Nice to have, moderate impact
- **P3 - Low**: Future considerations, nice ideas

## Size Estimates
- **S**: Small (< 1 day)
- **M**: Medium (1-3 days)
- **L**: Large (1-2 weeks)
- **XL**: Extra Large (2+ weeks)

---

## UI/UX Improvements

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Fix medium-size layouts (rankings shrink) | P0 | M | Responsive breakpoint issues |
| Front page refresh | P1 | M | General improvements needed |

---

## User Accounts & Social Features

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Basic user accounts | P1 | L | Foundation for all user features |
| Authentication options (Google, Facebook, gaming sites) | P2 | M | OAuth integration |
| "Played" tracking | P1 | M | Core user value |
| "Want to play" tracking | P1 | M | Core user value |
| Date tracking for plays | P3 | S | When did I play this? |
| Custom lists | P1 | L | Personal curation |
| Shareable lists | P2 | M | Social sharing URLs |
| Multiple list types ("best puzzle", "favorites", etc.) | P2 | M | Like RYM's list system |
| Personal descriptions for lists/items | P3 | M | User-written content |
| Export lists to CSV | P2 | S | Data portability |
| Written reviews | P2 | L | User-generated content |
| Ratings (fine-grained out of 100) | P2 | M | Personal scoring |
| "What should I play next" randomizer | P3 | S | Fun discovery feature |
| Email notifications (new lists, features) | P3 | M | Engagement |
| User messaging | P3 | L | Social feature |
| Share to social media | P2 | S | External sharing |
| Feature random user list on front page | P3 | S | Community spotlight |

---

## Discovery & Filtering

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Ranking vs. popularity weighting slider | P1 | XL | RYM-inspired; find obscure gems vs popular titles. May require algorithm rework. Potential premium feature. |
| Save/bookmark searches | P2 | M | Like RYM's saved charts |
| "If you like this game you may like X" recommendations | P2 | L | Based on genre, era, tags |
| Option to only show unplayed games | P2 | S | Requires user accounts |
| Timeline mode (scroll by year/decade) | P2 | L | Historical exploration |

---

## Game Record Expansion

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Game quotes | P2 | M | LLM-assisted extraction, feature random quote in header |
| Transparent ranking score display | P3 | S | Algorithm transparency |
| Playtime data (HowLongToBeat integration) | P2 | L | External API integration |
| Estimate total playtime for "want to play" lists | P3 | M | Depends on HLTB integration |
| Tags (subject matter: fantasy, sci-fi; mood: cozy, scary) | P1 | XL | LLM-assisted or user-voted. Enhances filtering and recommendations. RYM has this. |
| Country of developer | P3 | S | Additional metadata |
| YouTube longplay links | P3 | S | External links |
| speedrun.com info | P3 | M | External API |
| Series concept | P2 | L | Beyond autocomplete; enables series rankings and trend tracking |
| Better synopsis | P3 | L | IGDB descriptions are mediocre |

---

## Developer Pages

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Sort options for developers list | P2 | S | Basic usability |
| Best developers ranking | P2 | M | Like thegreatestbooks.org authors |
| Number of games stat | P3 | S | Simple addition |
| Best debut games by studio | P3 | M | Interesting angle |

---

## Lists Page

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Display list publication reputation/weight | P3 | M | Pro: Transparency. Con: Potential backlash |
| Sort game's lists by algorithm weight | P3 | S | Depends on above |
| Historic snapshots & comparison | P3 | L | Track ranking movement over time |

---

## Statistics & Analytics

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Years with most all-time great releases | P2 | M | Interesting data viz |
| Platform with highest placements | P2 | S | Simple query |
| User's most played genres | P2 | M | Requires user accounts |
| Compare personal vs. overall rankings | P2 | M | User engagement |
| User taste profile ("Spotify Wrapped" style) | P3 | L | LLM-generated insights |

---

## Algorithm & Transparency

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Algorithm explanation page | P2 | M | Documentation and transparency |
| User-configurable algorithm weights | P3 | XL | Very ambitious |

---

## Integrations

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Links to Backloggd / HowLongToBeat / etc | P2 | S | Simple external links |
| Import lists from other sites | P3 | L | Complex parsing |

---

## Content & Community

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Release calendar (upcoming releases) | P2 | L | New content type |
| Ranking movers (newly added, biggest moves) | P2 | M | Track changes |
| List submission form | P2 | M | User contributions |
| Discord server | P2 | S | Community building (external) |
| Community polls | P3 | M | Engagement feature |

---

## Monetization

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Affiliate links (GOG) | P2 | S | Non-intrusive revenue |
| Patreon | P3 | S | Community support |
| Premium features (ranking slider, etc.) | P3 | M | Requires feature work first |

---

## Multi-Media Expansion

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Generalized data model for other media | P3 | XL | Books, music, etc. Wait for book data schema |
| Upload scripts for other data models | P3 | L | Depends on schema |
| Cross-medium tag filtering | P3 | XL | Unique feature: "best sci-fi across games, movies, etc." |
| Rebranding/renaming | P3 | M | If expanding beyond games |

---

## Agentic AI Features

*See [agentic-ai-features.md](agentic-ai-features.md) for detailed technical specs and architecture.*

These features leverage LLMs (Claude) and potentially LangGraph for intelligent, conversational experiences. They require significant infrastructure investment (vector database, embedding pipeline, API cost management) and are lower priority until core user features are established.

### User-Facing AI Features

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| "Why is this game ranked here?" explainer | P2 | L | Generates explanation with list citations. Lowest complexity AI feature. Good starting point. |
| Conversational game discovery | P3 | XL | Natural language search: "Zelda but darker with horror elements". Requires intent parsing + semantic search. |
| Game comparison agent | P3 | L | Structured comparison of 2-3 games with insights beyond raw data. |
| "Ask about any game" agent | P3 | L | Answer questions like "Is Hollow Knight worth it if I don't like hard games?" |
| Personalized recommendation agent | P3 | XL | Learns preferences through interaction. Requires user accounts + conversation memory. |

### Backend AI Pipelines

| Feature | Priority | Size | Notes |
|---------|----------|------|-------|
| Semantic search (RAG) | P3 | XL | Vector embeddings for theme/mood search ("games about grief"). Requires pgvector or similar. |
| Content enrichment pipeline | P3 | XL | Auto-fill missing descriptions, historical context, development stories. Human review queue for edge cases. |
| List trend analysis agent | P3 | L | Analyze 700+ lists for rising/falling games, genre trends, etc. |

### AI Infrastructure Requirements

| Component | Priority | Size | Notes |
|-----------|----------|------|-------|
| Vector database (pgvector) | P3 | M | Required for semantic search and RAG features |
| Embedding pipeline | P3 | M | Generate/update embeddings for ~3000 games |
| LLM response caching | P3 | M | Essential for cost control at scale |
| Rate limiting / tiered access | P3 | S | Free tier limits, premium unlimited |

### AI Monetization Potential

- Premium AI features (unlimited conversational search, personalized recs)
- API access for affiliates
- Publisher insights ("why isn't my game ranking higher?")

---

## Suggested Implementation Phases

### Phase 1: Foundation
- Fix medium-size layouts (P0)
- Front page improvements (P1)
- Basic user accounts (P1)

### Phase 2: Core User Features
- Played/Want to play tracking (P1)
- Custom lists (P1)
- Tags system (P1)

### Phase 3: Discovery & Engagement
- Ranking vs. popularity slider (P1)
- Recommendations ("if you like...") (P2)
- Save/bookmark searches (P2)

### Phase 4: Expansion
- Statistics page (P2)
- Developer rankings (P2)
- Integrations (P2)

### Phase 5: Long-term
- Multi-media expansion (P3)
- Premium features & monetization (P3)
- Community features (P3)

### Phase 6: AI Features (Future)
- "Why is this ranked here?" explainer (P2) - lowest complexity starting point
- Semantic search / RAG infrastructure (P3)
- Conversational discovery & recommendations (P3)

---

## Ideas Marked as Low Enthusiasm

These ideas were flagged as potentially less valuable:
- Better synopsis (IGDB is "eh" but effort may not be worth it)
- Community polls (engagement vs. effort tradeoff)
- User taste profile / Spotify Wrapped style (fun but complex)
