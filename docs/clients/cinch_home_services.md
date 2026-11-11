# Cinch Home Services — prospect brief

Prepared 2026-11-11 for the first conversation. Desk research only: the brand
site was not reachable from the build environment, so facts come from Cinch's
press releases and newsroom listings, partner contract PDFs, and third-party
reviews (NerdWallet, ConsumerAffairs, This Old House, Money, Today's Homeowner,
Best Company). Anything that should go into a brand fact is marked VERIFY.

The import-ready tenant config is `seeds/cinch.yaml`. This document is the
"why" behind it.

## 1. The brand in one page

**What they are.** A national home warranty (home protection plan) provider
headquartered in Boca Raton, Florida. Roots go back to 1978 as Cross Country
Home Services, which also traded as HMS Home Warranty and TotalProtect. The
company rebranded to Cinch Home Services in 2019 and described itself then as
the second-largest home warranty provider in the US, behind American Home
Shield. It is a member of The Cross Country Group. The contract-issuing
subsidiary is HomeSure Services.

**What they sell.** Three plan tiers. Reviews still name them Appliance,
Built-in Systems and Complete Home; NerdWallet's 2026 review says the lineup
was restructured as Repair Only, Repair + Replace and Repair + Replace
Premier, on the stated logic that repairs are far likelier than replacements.
Pricing quoted across sources runs from about $28 to $68 a month with a
selectable service call fee ($75, $100 or $125 in recent reviews). VERIFY the
current plan names and prices before any of this becomes a brand fact.

**How they differentiate.** The contract terms reviewers single out:

- 180-day workmanship guarantee, against a 30-day industry norm.
- Covers mechanical failure from rust, corrosion and sediment, which most
  rivals exclude.
- Covers unknown pre-existing conditions (not detectable by visual inspection
  or simple mechanical test before coverage began).
- Complete Home (or the top tier) reimburses up to $500 of a homeowners
  insurance deductible.
- Appliance Buyline, a discount program on new brand-name appliances.
- Standard 30-day waiting period. Caps reported at $10,000 aggregate per term
  and $2,000 per kitchen or laundry appliance (VERIFY).
- Not sold in a handful of states (a training guide lists AK, HI, IA, MA, UT;
  reviews say "47 states" or "48 states"). VERIFY.

**How they sell.** Three channels, and they behave differently:

1. **Direct to homeowners** through the website and the review-site funnels.
2. **Real estate.** The HMS legacy. Brokerages such as Sibcy Cline describe a
   relationship of more than thirty years; Berkshire Hathaway HomeServices
   affiliates, RE/MAX and Long & Foster materials carry Cinch contracts or
   white-labelled versions. Seller coverage is free where the law allows if the
   buyer's annual plan is bought at closing.
3. **Partners.** Utilities and energy retailers (Kiwi Energy's "Kiwi Guard
   powered by Cinch", Spring Power & Gas, New York utility programs, TXU's
   MyHome Systems Protect documentation), insurers and distributors (a
   Progressive home warranty page and bolttech product sheets reference Cinch),
   banks and retailers. Sears Home Warranty is administered by Cinch and Sears
   technicians service Cinch claims, so Sears is a channel, not a rival.

**Reputation, which is the story.** Cinch holds the kind of split that AI
engines surface verbatim:

| Source | Signal |
|---|---|
| ConsumerAffairs 2026 | 4.1 of 5 on more than 12,000 reviews, named Best Overall; Buyer's Choice award for Best Value for Price |
| U.S. News & World Report 2026 | Best Home Warranty Company for HVAC |
| Stevie Awards, Jan 2026 | Gold for customer experience, Bronze for technology in customer service |
| Newsweek 2026 | America's Greatest Midsize Workplaces |
| BBB | Roughly 1.1 of 5 on about 1,600 customer reviews; dispatch delays and coverage-cap disputes are the recurring themes |
| Best Company | 3.4 of 5 |

Ask an engine "are Cinch reviews good or bad" and the answer depends entirely
on which of these it retrieves. That is measurable, and it is the first chart
to show them.

**Who is buying now.** A new marketing leadership team:

- Sharena Ali, CEO.
- Casey Hurbis, Chief Marketing Officer, appointed October 2026, owning brand
  strategy. A CMO four weeks into the job wants a baseline.
- Jessica Fields, Chief Commercial Officer, and Keith L. Johnson, Chief Data &
  Analytics Officer, both April 2026, with a stated mandate to expand
  strategic partnerships. The partner corpus in the seed is for them.
- A Habitat for Humanity partnership and local trades-education sponsorships
  in Palm Beach and Broward counties give a community story that engines
  currently do not tell.

## 2. Why this category is an EverPresent category

- **Research-heavy, affiliate-ranked.** Home warranty buyers compare before
  they buy, and the pages engines cite are ConsumerAffairs, NerdWallet, This
  Old House, Money and Today's Homeowner. The Citations screen and third-party
  targeting are the product here, not an add-on.
- **Rivals already write the comparison.** Liberty Home Guard publishes its own
  "Liberty Home Guard vs. Cinch" page; ConsumerAffairs publishes a dozen
  "Cinch vs X" pages. Cinch does not control the head-to-head narrative.
- **An ambiguous name.** "Cinch" is also a UK used-car retailer, a jeans
  brand, a belt brand and an ordinary word. Mention detection needs the
  specific aliases in the seed, and one branded prompt watches for
  disambiguation drift.
- **Dead names in the training data.** Cross Country Home Services, HMS and
  TotalProtect still appear in contracts, reviews and model weights. The seed
  keeps them as aliases so legacy mentions still attribute to Cinch, and a
  branded prompt checks whether engines describe Cinch by a name it dropped in
  2019.
- **Plan names just changed.** Engines answering from weights will quote the
  old tier names and old prices. That is the accuracy demo.
- **Three buyers, three vocabularies.** Homeowners ask "is it worth it",
  agents ask "what should I recommend", partner managers ask "who can
  white-label this". Each gets its own corpus so the Scorecard topic view
  reads as a channel view.

## 3. Personas

Persona wording is frozen once the first run completes. Each runs only on the
prompts that name it; the generic baseline runs on everything.

| Segment | Who | Why they are in |
|---|---|---|
| `generic` | No persona | Baseline and trend line |
| `first_time_buyer` | Closing in three weeks, inspection flagged old furnace and water heater, savings depleted | The closing-table sale. Highest-intent moment Cinch has |
| `aging_home_owner` | Twelve years in the house, AC and appliances ageing, one big bill would hurt | The direct-channel core buyer; the HVAC award should land here |
| `landlord` | Three single-family rentals in two cities, self-managed | Distinct eligibility rules and a distinct value story (no contractor chasing) |
| `current_customer` | Already has a Cinch plan | Service accuracy and sentiment on branded prompts; churn moments |
| `listing_agent` | Twenty closings a year, recommends a warranty, gets blamed for bad claims | The HMS channel. One overlay runs the seller-side variant |
| `partner_buyer` | Product manager at a regional energy retailer with 400,000 customers | Optional in phase 1. The only persona that measures the partner pipeline; include it if the Commercial team is in the room |

A home seller is handled as an overlay on `listing_agent` rather than a
seventh persona, to keep persona count (and browser-run cost) down.

## 4. Prompt set

43 prompts in ten corpora. 11 are branded (they name Cinch, so they measure
brand knowledge and sentiment, not competitive visibility). 82 baseline-plus-
persona runs per engine per sample; at nine surfaces that is about 740 answers
a sample, which is in line with the Botnia and GoDaddy tenants.

| Corpus | Prompts | What it measures |
|---|---|---|
| `is_it_worth_it` | 4 | Whether Cinch appears when the category itself is on trial ("home warranties are a scam") |
| `best_providers` | 6 | The head terms, plus the three contract differentiators (rust, pre-existing, 180-day guarantee) asked as buyer questions |
| `home_buying_closing` | 4 | The negotiation moment: who pays, which company to ask the seller for, transferability |
| `real_estate_pro` | 4 | What engines tell agents to recommend; seller coverage; agent programs |
| `hvac_appliances` | 4 | Problem-first prompts (15-year-old AC, water heater caps, kitchen appliances, Appliance Buyline) |
| `landlord_rental` | 2 | Rental eligibility and multi-property accounts |
| `competitive` | 5 | AHS, Liberty Home Guard and First American head-to-heads, plus two unbranded conquest prompts |
| `brand_knowledge` | 7 | Legitimacy, legacy names, pricing, reviews, claims, waiting period, cancellation |
| `partner_b2b` | 4 | White-label providers for utilities, HomeServe alternatives, insurer and bank administrators |
| `agent_task` | 3 | "Decide for me" prompts; which brand the engine reaches for first |

**Read these first after run one:**

1. "What home warranty companies are similar to Cinch?" shows the peer set
   engines place Cinch in. If it is Choice and Select rather than AHS and
   First American, that is the positioning problem in one answer.
2. "Are Cinch Home Services reviews good or bad?" shows which reputation
   source each engine trusts.
3. "What do Cinch Home Services plans cost and what's the service fee?" shows
   how stale each engine's pricing and plan names are.
4. "What's the best home warranty for an older house with original HVAC and
   appliances?" shows whether the U.S. News HVAC award has reached the
   engines at all.
5. "Which companies provide white-label home warranty plans for utilities?"
   shows whether Cinch or HomeServe owns the partner conversation.

## 5. Brand facts

Active now (corroborated across several independent sources):

- Workmanship guarantee is 180 days.
- Waiting period is 30 days.
- Cinch Home Services is not the UK used-car retailer (disambiguation guard).
- Headquartered in Boca Raton, not the old Fort Lauderdale address.

Held back until Cinch confirms (commented in the seed): starting price,
service fee options, aggregate cap, state availability. A wrong ground truth
makes correct answers look wrong, so these stay off until onboarding.

## 6. Questions for the first call

1. Current plan names and price points by state, and the service fee menu.
2. Which channel the engagement is for: direct, real estate, or partner. It
   changes which persona runs and which corpus leads the report.
3. Rental and multi-property eligibility, so the landlord prompts are honest.
4. Whether the Sears Home Warranty relationship should be measured as Cinch
   visibility or kept separate.
5. Whether Long & Foster, Progressive and other white-labelled plans should
   attribute to Cinch (they can be added as alias domains).
6. Who owns the review-site relationships today, since those pages are where
   the citations will come from.

## 7. Sources

- Cinch newsroom and press releases: CMO appointment (Oct 2026), executive
  appointments (Apr 2026), Board of Advisors (Jan 2026), U.S. News and
  ConsumerAffairs awards (Jul 2026), Newsweek (Jun 2026), Stevie Awards
  (Jan 2026), Habitat for Humanity partnership, utility partner page.
- NerdWallet, "Cinch Home Services Home Warranty Review 2026".
- ConsumerAffairs, Cinch profile and the "Cinch vs" comparison pages; "Best
  Home Warranty Companies of 2026".
- This Old House, Money, Today's Homeowner, Best Company, CNN Underscored
  reviews of Cinch.
- Liberty Home Guard, "Liberty Home Guard vs. Cinch Home Services".
- RISMedia coverage of Cinch's real estate programs; Sibcy Cline and BHHS
  affiliate warranty pages; RE/MAX-hosted Cinch contract PDF; bolttech Cinch
  product sheet and training guide; TXU MyHome Systems Protect terms.
- PHCP Pros and PR Newswire on the 2019 rebrand from Cross Country Home
  Services; Warranty Week archive; Justia trademark records for HomeSure.
- Kiwi Energy and Spring Power & Gas partnership announcements.
