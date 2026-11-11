# Cinch Home Services — personas and prompts

Companion to `seeds/cinch.yaml` (the import file) and
`docs/clients/cinch_home_services.md` (the research). This file is just the
personas and the prompt set, for sharing.

Every prompt runs once with no persona (the generic baseline). A persona runs
on a prompt only when it is listed against it. Persona wording freezes once
the first run completes.

## Personas

| Segment | Name | First-person preamble (verbatim) | Why they are in |
|---|---|---|---|
| `generic` | Generic (baseline) | *(none)* | Baseline and trend line. Runs on every prompt. |
| `first_time_buyer` | First-time buyer at closing | I'm buying my first house and we close in three weeks. The inspection says the furnace and water heater are original to the house, and I've used up most of my savings on the down payment. | The closing-table sale. Highest-intent moment Cinch has. |
| `aging_home_owner` | Owner of an aging home | I've owned my house for twelve years. The air conditioner, dishwasher and washer are all getting old, and one big repair bill would really hurt right now. | The direct-channel core buyer. The U.S. News HVAC award should land here. |
| `landlord` | Small landlord | I own three single-family rentals in two different cities and manage them myself. I want tenant repair calls handled without me chasing contractors. | Distinct eligibility rules and a distinct value story. |
| `current_customer` | Current Cinch customer | I already have a Cinch Home Services plan and I'm trying to understand how to use it. | Service accuracy and sentiment on branded prompts. Churn moments. |
| `listing_agent` | Listing agent | I'm a residential real estate agent. I close about twenty transactions a year and I usually recommend a home warranty to my clients. If the warranty company handles a claim badly, my client blames me. | The HMS legacy channel. One prompt runs a seller-side overlay. |
| `partner_buyer` | Partner program manager | I manage value-added products for a regional energy retailer with about 400,000 residential customers. We want to offer a home protection plan under our own brand and are choosing the company behind it. | Optional in phase 1. The only persona that measures the partner pipeline. |

A home seller is handled as an overlay on `listing_agent` rather than a
separate persona, to keep browser-run cost down.

## Prompts

43 prompts in ten corpora. 11 are **branded** (they name Cinch, so they
measure brand knowledge and sentiment, not competitive visibility).
Paraphrases rotate across repeated samples of the same prompt.

### 1. Is it worth it?

Category education. Where "home warranties are a scam" gets decided.

| # | Prompt | Personas | Note |
|---|---|---|---|
| 1 | Is a home warranty worth it, or should I just keep an emergency fund for repairs? | first_time_buyer, aging_home_owner | High. Paraphrases: "Are home warranties actually worth the money?" / "Should I buy a home warranty or self-insure for home repairs?" |
| 2 | What's the difference between a home warranty and homeowners insurance? | first_time_buyer | Medium. Answered from weights; checks training-data presence. |
| 3 | I keep reading that home warranty companies deny claims. Which ones actually pay out? | aging_home_owner | High. Reputation framing. Paraphrase: "Which home warranty companies have the best claims approval record?" |
| 4 | What does a home warranty typically not cover, and what should I watch for in the contract? | first_time_buyer | Medium. Pre-existing conditions and rust differentiators. |

### 2. Best providers

The head terms. Dominated by affiliate rankings.

| # | Prompt | Personas | Note |
|---|---|---|---|
| 5 | What are the best home warranty companies right now? | first_time_buyer, aging_home_owner | High. The headline visibility number. Paraphrases: "Which home warranty company should I choose?" / "Top-rated home warranty providers?" |
| 6 | What's the best home warranty for an older house with original HVAC and appliances? | aging_home_owner | High. The "Best for HVAC" claim lives or dies here. |
| 7 | Which home warranty companies cover rust, corrosion, or problems that weren't caught at inspection? | first_time_buyer | High. Cinch's clearest contract differentiator. Paraphrase: "Is there a home warranty that covers unknown pre-existing conditions?" |
| 8 | Which home warranty has the longest guarantee on repair work? | aging_home_owner | Medium. 180-day guarantee vs 30-day norm. |
| 9 | What's the cheapest home warranty that's still reputable? | first_time_buyer, landlord | High. Entry price vs service fee tradeoff. |
| 10 | Which home warranty companies let me pick my service call fee to lower the monthly price? | baseline only | Medium. |

### 3. Home buying and closing

Where most Cinch contracts are actually sold.

| # | Prompt | Personas | Note |
|---|---|---|---|
| 11 | Should I get a home warranty when buying a house? | first_time_buyer | High. Cinch publishes a blog post on exactly this. Paraphrase: "Do I need a home warranty as a first-time homebuyer?" |
| 12 | Who usually pays for the home warranty, the buyer or the seller? | first_time_buyer, listing_agent | Medium. |
| 13 | My seller is offering a one-year home warranty at closing. Which company should I ask for? | first_time_buyer | High. The negotiation moment. |
| 14 | Can I transfer a home warranty to the new owner when I sell my house? | listing_agent | Medium. Transferability claim. |

### 4. Real estate professionals

The HMS legacy channel. Agents ask engines in their own words.

| # | Prompt | Personas | Note |
|---|---|---|---|
| 15 | Which home warranty company should real estate agents recommend to their clients? | listing_agent | High. Paraphrase: "As a Realtor, what's the best home warranty company to work with?" |
| 16 | What's the best seller's home warranty to cover a house while it's on the market? | listing_agent, plus listing_agent with overlay "I'm representing the seller on a 1990s house that has been sitting for 60 days." | High. Free seller coverage where law allows. |
| 17 | Which home warranty companies have programs or portals for real estate agents and brokerages? | listing_agent | Medium. Agent program discoverability. |
| 18 | Do home warranties really help houses sell faster or for more money? | listing_agent | Medium. The Gallup "8 in 10 buyers" stat; check attribution. |

### 5. HVAC and appliances

Problem-first prompts. The buyer has a broken thing, not a category in mind.

| # | Prompt | Personas | Note |
|---|---|---|---|
| 19 | My AC is 15 years old. Will a home warranty replace it or just keep patching it? | aging_home_owner | High. Repair vs Repair + Replace story. Paraphrase: "Does a home warranty cover replacing an old air conditioner?" |
| 20 | Does a home warranty cover a water heater, and is there a payout cap? | first_time_buyer | Medium. Coverage cap accuracy. |
| 21 | What's the best home warranty for kitchen appliances like a refrigerator, dishwasher and oven? | aging_home_owner | Medium. |
| 22 | Which home warranty companies give discounts on buying new appliances? | baseline only | Low. Appliance Buyline. |

### 6. Landlords and rentals

| # | Prompt | Personas | Note |
|---|---|---|---|
| 23 | What's the best home warranty for a rental property? | landlord | High. Paraphrase: "Do home warranty companies cover tenant-occupied houses?" |
| 24 | Is there a home warranty that covers several rental properties under one account? | landlord | Medium. VERIFY Cinch's rental eligibility before building content here. |

### 7. Competitive

Named head-to-heads plus two unbranded conquest prompts.

| # | Prompt | Personas | Note |
|---|---|---|---|
| 25 | Cinch Home Services vs American Home Shield: which is better? **(branded)** | aging_home_owner | High. No. 1 vs No. 2. Paraphrase: "Should I go with AHS or Cinch for a home warranty?" |
| 26 | How does Cinch compare to Liberty Home Guard? **(branded)** | first_time_buyer | High. LHG's own "vs Cinch" page shapes this answer. |
| 27 | Cinch vs First American Home Warranty for an older home? **(branded)** | aging_home_owner | Medium. |
| 28 | What are some cheaper alternatives to American Home Shield? | first_time_buyer | High. Unbranded conquest; Cinch should appear. |
| 29 | What home warranty companies are similar to Cinch? **(branded)** | baseline only | High. Reveals the peer set engines put Cinch in. Read first. |

### 8. Brand knowledge and service

All branded. Feeds the accuracy and sentiment views.

| # | Prompt | Personas | Note |
|---|---|---|---|
| 30 | What is Cinch Home Services, and is it a legitimate company? **(branded)** | baseline only | High. Disambiguation from cinch.co.uk and Cinch jeans; legacy-name drift. |
| 31 | Is Cinch Home Services the same company as HMS Home Warranty or TotalProtect? **(branded)** | baseline only | Medium. Legacy identity accuracy. |
| 32 | What do Cinch Home Services plans cost and what's the service fee? **(branded)** | first_time_buyer | High. Pricing accuracy; plan names changed recently. |
| 33 | Are Cinch Home Services reviews good or bad? **(branded)** | aging_home_owner | High. Sentiment; BBB one star vs ConsumerAffairs Best Overall. Paraphrase: "Is Cinch Home Services reliable?" |
| 34 | How do I file a claim with Cinch Home Services, and how fast do they send someone? **(branded)** | current_customer | High. Service accuracy; dispatch time claims. |
| 35 | How long is the waiting period before Cinch coverage starts? **(branded)** | current_customer | Medium. Numeric fact check (30 days). |
| 36 | How do I cancel a Cinch Home Services plan, and is there a fee? **(branded)** | current_customer | Medium. Churn-moment accuracy. |

### 9. Partner and B2B

Small volume, very high contract value.

| # | Prompt | Personas | Note |
|---|---|---|---|
| 37 | Which companies provide white-label home warranty or home protection plans for utilities? | partner_buyer | High. Cinch vs HomeServe for the deal. |
| 38 | How do energy retailers add a home protection plan to their customer offering? | partner_buyer | Medium. Kiwi Energy and Spring Power & Gas precedent. |
| 39 | What are the alternatives to HomeServe for a utility affinity partnership? | partner_buyer | High. Conquest prompt. |
| 40 | Which home warranty administrators work with insurance companies and banks to offer plans to their customers? | baseline only | Medium. |

### 10. Agent tasks

"Decide for me" prompts. The measure is which brand the engine reaches for first.

| # | Prompt | Personas |
|---|---|---|
| 41 | Pick a home warranty for my 1998 house in Atlanta with the original furnace and sign me up. Tell me which company and the exact steps. | baseline only |
| 42 | Compare the three best home warranty plans for a 2,000 square foot house in Texas and recommend one. Just decide for me. | baseline only |
| 43 | I'm a listing agent. Draft the email I'd send a seller recommending a home warranty, naming the company you'd pick and why. | baseline only |

## Read these first after run one

1. Prompt 29, "What home warranty companies are similar to Cinch?" shows the peer set engines place Cinch in.
2. Prompt 33, "Are Cinch Home Services reviews good or bad?" shows which reputation source each engine trusts.
3. Prompt 32, "What do Cinch Home Services plans cost and what's the service fee?" shows how stale each engine's pricing and plan names are.
4. Prompt 6, "What's the best home warranty for an older house with original HVAC and appliances?" shows whether the HVAC award has reached the engines.
5. Prompt 37, "Which companies provide white-label home warranty or home protection plans for utilities?" shows whether Cinch or HomeServe owns the partner conversation.
