"""
===========================================
AI NEGOTIATION AGENT - INTERVIEW TEMPLATE
===========================================

Welcome! Your task is to build a BUYER agent that can negotiate effectively
against our hidden SELLER agent. Success is measured by achieving profitable
deals while maintaining character consistency.

INSTRUCTIONS:
1. Read through this entire template first
2. Implement your agent in the marked sections
3. Test using the provided framework
4. Submit your completed code with documentation

"""

import json
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod
import random

# ============================================
# PART 1: DATA STRUCTURES (DO NOT MODIFY)
# ============================================

@dataclass
class Product:
    """Product being negotiated"""
    name: str
    category: str
    quantity: int
    quality_grade: str  # 'A', 'B', or 'Export'
    origin: str
    base_market_price: int  # Reference price for this product
    attributes: Dict[str, Any]

@dataclass
class NegotiationContext:
    """Current negotiation state"""
    product: Product
    your_budget: int  # Your maximum budget (NEVER exceed this)
    current_round: int
    seller_offers: List[int]  # History of seller's offers
    your_offers: List[int]  # History of your offers
    messages: List[Dict[str, str]]  # Full conversation history

class DealStatus(Enum):
    ONGOING = "ongoing"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


# ============================================
# PART 2: BASE AGENT CLASS (DO NOT MODIFY)
# ============================================

class BaseBuyerAgent(ABC):
    """Base class for all buyer agents"""
    
    def __init__(self, name: str):
        self.name = name
        self.personality = self.define_personality()
        
    @abstractmethod
    def define_personality(self) -> Dict[str, Any]:
        """
        Define your agent's personality traits.
        
        Returns:
            Dict containing:
            - personality_type: str (e.g., "aggressive", "analytical", "diplomatic", "custom")
            - traits: List[str] (e.g., ["impatient", "data-driven", "friendly"])
            - negotiation_style: str (description of approach)
            - catchphrases: List[str] (typical phrases your agent uses)
        """
        pass
    
    @abstractmethod
    def generate_opening_offer(self, context: NegotiationContext) -> Tuple[int, str]:
        """
        Generate your first offer in the negotiation.
        
        Args:
            context: Current negotiation context
            
        Returns:
            Tuple of (offer_amount, message)
            - offer_amount: Your opening price offer (must be <= budget)
            - message: Your negotiation message (2-3 sentences, include personality)
        """
        pass
    
    @abstractmethod
    def respond_to_seller_offer(self, context: NegotiationContext, seller_price: int, seller_message: str) -> Tuple[DealStatus, int, str]:
        """
        Respond to the seller's offer.
        
        Args:
            context: Current negotiation context
            seller_price: The seller's current price offer
            seller_message: The seller's message
            
        Returns:
            Tuple of (deal_status, counter_offer, message)
            - deal_status: ACCEPTED if you take the deal, ONGOING if negotiating
            - counter_offer: Your counter price (ignored if deal_status is ACCEPTED)
            - message: Your response message
        """
        pass
    
    @abstractmethod
    def get_personality_prompt(self) -> str:
        """
        Return a prompt that describes how your agent should communicate.
        This will be used to evaluate character consistency.
        
        Returns:
            A detailed prompt describing your agent's communication style
        """
        pass


# ============================================
# PART 3: YOUR IMPLEMENTATION STARTS HERE
# ============================================

class YourBuyerAgent(BaseBuyerAgent):
    """
    Professional Strategist (Enhanced)

    Enhancements compared to the original:
    - Personality Adaptation: analyzes seller messages and switches tactic (cold/logical vs warm/appeal)
    - Concession Tracking & Reciprocity: records all concessions and asks for value in return when it concedes
    - Keeps deterministic numeric negotiation behavior but augments messages with reciprocity demands

    Objectives:
    - Remain unemotional and tactical when opponent is emotional
    - If opponent is cold/logical, optionally add a personal appeal to destabilize them
    - Never exceed budget
    """

    # ---- Tunable hyperparameters (deterministic) ----
    MIN_STEP = 1000
    AGG_OPEN_BUDGET_RATIO = 0.78
    MARKET_OPEN_RATIO = 0.72
    WALKAWAY_MARKET_RATIO = 0.96
    FAST_CONCESSION_AFTER = 5
    FAST_CONCESSION_MULT = 1.5
    EST_DECAY = 0.6
    MIN_SELLER_MARGIN = 1.10
    SAVINGS_THRESHOLD = 0.10

    def define_personality(self) -> Dict[str, Any]:
        return {
            "personality_type": "professional_strategist",
            "traits": ["calm", "tactical", "adaptive", "reciprocal"],
            "negotiation_style": (
                "Calm, data-driven and adaptive. Prioritizes win-win outcomes but enforces reciprocity. "
                "If the counterpart is emotional, remain logical; if counterpart is cold/logical, use subtle appeal to gain concessions."
            ),
            "catchphrases": [
                "Let's be rational and efficient.",
                "I move when you reciprocate.",
                "Numbers steer this conversation."
            ]
        }

    # ---------- State helpers ----------
    def _init_state(self, context: NegotiationContext):
        if not hasattr(self, "_state"):
            self._state = {
                "seller_history": [],
                "min_seller_seen": None,
                "seller_min_est": None,
                # concession tracking
                "concessions": {"buyer": [], "seller": []},
                # last observed tone
                "last_seller_tone": "neutral",
            }

    def _format_professional(self, content: str) -> str:
        lead = random.choice(["For clarity:", "Let's be direct:", "To be efficient:", "Straightforwardly:"])
        tail = random.choice(["Please confirm.", "I expect a prompt response.", "Proceed accordingly.", "This suits my thresholds."])
        return f"{lead} {content} {tail}"

    # ---------- Emotion / Tone analysis ----------
    def analyze_seller_tone(self, text: str) -> str:
        """Simple heuristic tone detection: 'emotional' or 'logical' or 'neutral'"""
        if not text:
            return "neutral"
        t = text.lower()
        # keywords that often indicate emotional language
        emotional = ["angry", "insult", "unfair", "frustrat", "outrage", "hate", "never", "demand", "disrespect", "!", "how dare"]
        polite_indicators = ["please", "kindly", "thank", "appreciate"]
        logical_indicators = ["market", "price", "cost", "margin", "percent", "%", "data", "analysis", "based on"]

        score = 0
        for kw in emotional:
            if kw in t:
                score -= 2
        for kw in logical_indicators:
            if kw in t:
                score += 1
        for kw in polite_indicators:
            if kw in t:
                score += 1

        if score <= -1:
            return "emotional"
        if score >= 1:
            return "logical"
        return "neutral"

    def personality_adaptation(self, seller_message: str) -> str:
        tone = self.analyze_seller_tone(seller_message)
        self._state["last_seller_tone"] = tone
        # Rule: emotional -> stay logical; logical -> use slight appeal
        if tone == "emotional":
            return "logical"
        if tone == "logical":
            return "appeal"
        return "logical"

    # ---------- Concession tracking & reciprocity ----------
    def _record_concession(self, actor: str, amount: int):
        st = self._state
        st["concessions"][actor].append(amount)

    def _seller_made_concession(self, new_seller_price: int) -> Optional[int]:
        """Detect if seller reduced price compared to last seen; return concession magnitude"""
        st = self._state
        hist = st["seller_history"]
        if not hist:
            return None
        last = hist[-1]
        if new_seller_price < last:
            return last - new_seller_price
        return None

    def _format_reciprocity_request(self, buyer_concession_count: int) -> str:
        """Return a suitable non-price demand depending on how many times buyer has conceded"""
        demands = [
            "free delivery",
            "extended warranty (6 months)",
            "priority dispatch",
            "a small bulk discount on the next order",
            "payment terms (30 days)"
        ]
        idx = min(len(demands) - 1, buyer_concession_count - 1) if buyer_concession_count > 0 else 0
        return demands[idx]

    # ---------- Pricing helpers (same logic as original) ----------
    def _extract_price(self, text: str) -> Optional[int]:
        if not text:
            return None
        m = re.search(r"₹\s*([\d,]+)", text)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except:
                return None
        m2 = re.search(r"(\d{5,})", text)
        if m2:
            try:
                return int(m2.group(1))
            except:
                return None
        return None

    def _opening_offer_number(self, context: NegotiationContext) -> int:
        market = context.product.base_market_price
        budget = context.your_budget
        opening = min(int(budget * self.AGG_OPEN_BUDGET_RATIO), int(market * self.MARKET_OPEN_RATIO))
        return max(self.MIN_STEP, min(opening, budget))

    def _walkaway_cap(self, context: NegotiationContext) -> int:
        market = context.product.base_market_price
        return min(int(market * self.WALKAWAY_MARKET_RATIO), context.your_budget)

    def _update_seller_estimates(self, seller_price: int):
        st = self._state
        st["seller_history"].append(seller_price)

        if st["min_seller_seen"] is None:
            st["min_seller_seen"] = seller_price
        else:
            st["min_seller_seen"] = min(st["min_seller_seen"], seller_price)

        rough_floor = int(seller_price * 0.85)
        if st["seller_min_est"] is None:
            st["seller_min_est"] = rough_floor
        else:
            st["seller_min_est"] = int(self.EST_DECAY * st["seller_min_est"] + (1 - self.EST_DECAY) * rough_floor)

    def _closing_target_from_estimate(self, context: NegotiationContext) -> Optional[int]:
        st = self._state
        if not st["min_seller_seen"]:
            return None
        est_min_floor = int(st["min_seller_seen"] * 0.98)
        target = int(est_min_floor * self.MIN_SELLER_MARGIN)
        return max(self.MIN_STEP, target)

    # ---------- Required  ----------
    def generate_opening_offer(self, context: NegotiationContext) -> Tuple[int, str]:
        self._init_state(context)
        offer = self._opening_offer_number(context)
        name = context.product.name
        qty = context.product.quantity
        content = f"My opening is ₹{offer} for {qty} units of {context.product.quality_grade}-grade {name}."
        # Track initial buyer offer as a 'concession' step 0 (we note but don't demand yet)
        self._record_concession("buyer", offer)
        return offer, self._format_professional(content)

    def respond_to_seller_offer(self, context: NegotiationContext, seller_price: int, seller_message: str) -> Tuple[DealStatus, int, str]:
        self._init_state(context)
        # Analyze tone and update estimates
        observed = seller_price if seller_price is not None else self._extract_price(seller_message)
        if observed:
            # detect seller concession relative to last seen
            seller_conc = self._seller_made_concession(observed) if self._state["seller_history"] else None
            self._update_seller_estimates(observed)
            if seller_conc and seller_conc > 0:
                self._record_concession("seller", seller_conc)

        tone_adapt = self.personality_adaptation(seller_message)

        market = context.product.base_market_price
        budget = context.your_budget
        opening = self._opening_offer_number(context)
        walkaway = self._walkaway_cap(context)
        last_my = context.your_offers[-1] if context.your_offers else opening

        interview_threshold = int(budget * (1 - self.SAVINGS_THRESHOLD))
        market_floor_proxy = int(market * 0.82)

        # Immediate acceptance conditions (same as before)
        if seller_price is not None:
            if seller_price <= min(interview_threshold, walkaway):
                msg = f"I accept ₹{seller_price}. It meets my efficiency threshold."
                return DealStatus.ACCEPTED, seller_price, self._format_professional(msg)
            if seller_price <= min(walkaway, market_floor_proxy) and seller_price <= budget:
                msg = f"I accept ₹{seller_price}. This aligns with my market-floor analysis."
                return DealStatus.ACCEPTED, seller_price, self._format_professional(msg)

        closing_target = self._closing_target_from_estimate(context)
        if closing_target is not None:
            closing_target = min(closing_target, walkaway, budget)

        # Late-round finalization
        if context.current_round >= 9:
            if seller_price is not None and seller_price <= budget:
                msg = f"Finalizing at ₹{seller_price}."
                return DealStatus.ACCEPTED, seller_price, self._format_professional(msg)
            last_shot = min(budget, walkaway)
            if closing_target:
                last_shot = min(last_shot, max(interview_threshold, closing_target))
            # when making last shot, demand reciprocity proportional to buyer concessions
            buyer_conc_count = len(self._state["concessions"]["buyer"])
            demand = self._format_reciprocity_request(buyer_conc_count)
            msg = f"Final offer ₹{last_shot}. In return I require: {demand}. Immediate confirmation concludes the deal."
            return DealStatus.ONGOING, last_shot, self._format_professional(msg)

        # Normal-round dynamic target
        r = max(1, min(10, context.current_round))
        progress = (r - 1) / 9.0
        eased = progress ** 0.9
        dynamic_target = int(opening + (walkaway - opening) * eased)

        if seller_price is not None and seller_price <= min(dynamic_target, budget):
            msg = f"Agreed at ₹{seller_price}. Efficient resolution."
            return DealStatus.ACCEPTED, seller_price, self._format_professional(msg)

        if seller_price is None:
            proposed = min(budget, max(opening, int(last_my * 1.08)))
            content = f"My counter is ₹{proposed}. Provide a numeric offer to proceed."
            return DealStatus.ONGOING, proposed, self._format_professional(content)

        # Gap-driven step as original
        gap = max(0, seller_price - last_my)
        base_far = int(max(self.MIN_STEP, market * 0.06))
        base_close = int(max(self.MIN_STEP, market * 0.02))
        pct_gap = gap / max(1, last_my)

        if pct_gap > 0.18:
            step = base_far
        elif pct_gap > 0.07:
            step = int((base_far + base_close) / 2)
        else:
            step = base_close

        if r > self.FAST_CONCESSION_AFTER:
            step = int(step * self.FAST_CONCESSION_MULT)

        target_anchor = None
        if closing_target:
            target_anchor = max(interview_threshold, closing_target)
            target_anchor = min(target_anchor, walkaway, budget)

        if target_anchor:
            toward = max(step, int((target_anchor - last_my) * 0.5))
            proposed = last_my + max(self.MIN_STEP, toward)
        else:
            proposed = last_my + max(self.MIN_STEP, int(max(step, gap * 0.45)))

        proposed = max(proposed, opening, last_my)
        proposed = min(proposed, budget, walkaway)

        # If we are increasing our offer compared to last time, record buyer concession
        if proposed > last_my:
            self._record_concession("buyer", proposed - last_my)

        # Determine reciprocity demand if buyer already conceded more times than seller
        buyer_conc_count = len(self._state["concessions"]["buyer"])
        seller_conc_count = len(self._state["concessions"]["seller"])
        reciprocity_text = ""
        if buyer_conc_count > seller_conc_count:
            demand = self._format_reciprocity_request(buyer_conc_count)
            reciprocity_text = f" In return for this move I need: {demand}."

        # Tailor message tone based on adaptation
        if tone_adapt := tone_adapt if (tone_adapt := tone_adapt) else "logical":
            if tone_adapt == "logical":
                content = (
                    f"My counter is ₹{proposed}. This reflects market structure, my ceiling, and time-to-agreement." + reciprocity_text
                )
            else:  # appeal
                content = (
                    f"My counter is ₹{proposed}. I prefer to work with you — if you can include {self._format_reciprocity_request(buyer_conc_count)}, we can close today." +
                    " Let's make this a lasting cooperation."
                )
        else:
            content = f"My counter is ₹{proposed}." + reciprocity_text

        return DealStatus.ONGOING, proposed, self._format_professional(content)

    # ---------- Optional helpers ----------
    def analyze_negotiation_progress(self, context: NegotiationContext) -> Dict[str, Any]:
        last_seller = context.seller_offers[-1] if context.seller_offers else None
        last_buyer = context.your_offers[-1] if context.your_offers else None
        spread = (last_seller - last_buyer) if (last_seller and last_buyer) else None
        return {"round": context.current_round, "last_seller": last_seller, "last_buyer": last_buyer, "spread": spread}

    def calculate_fair_price(self, product: Product) -> int:
        market = product.base_market_price
        grade = (product.quality_grade or "").upper()
        if "EXPORT" in grade:
            return int(market * 1.02)
        if grade == "A":
            return int(market * 0.98)
        if grade == "B":
            return int(market * 0.92)
        return market

    def get_personality_prompt(self) -> str:
        return (
            "You are a professional strategist: calm, adaptive, and focused on win-win outcomes. "
            "If the opponent is emotional, remain logical. If opponent is cold/logical, use a mild appeal. "
            "Track concessions and always ask for reciprocity when giving ground. "
            "Never exceed your budget."
        )

class YourSellerAgent(BaseBuyerAgent):
    """
    Professional Strategist Seller (Enhanced)

    Enhancements compared to the base:
    - Personality Adaptation: responds logically to emotional buyers, appeals subtly to cold/logical buyers
    - Concession Tracking & Reciprocity: tracks concessions and requires non-price reciprocity when conceding
    - Tactical professional style, win-win but protects seller margin

    Objectives:
    - Remain unemotional and tactical when opponent is emotional
    - If opponent is cold/logical, add subtle personal appeal
    - Never go below minimum acceptable floor
    """
    def __init__(self, name: str = "ProfessionalSeller"):
        super().__init__(name=name)
    # ---- Tunable hyperparameters ----
    MIN_STEP = 1000
    AGG_OPEN_RATIO = 1.25        # Seller opening relative to market price
    MARKET_OPEN_RATIO = 1.15
    WALKAWAY_RATIO = 0.90        # Seller never goes below this fraction of market
    FAST_CONCESSION_AFTER = 5
    FAST_CONCESSION_MULT = 1.5
    EST_DECAY = 0.6
    MIN_BUYER_MARGIN = 0.92
    SAVINGS_THRESHOLD = 0.08

    def define_personality(self) -> Dict[str, Any]:
         return {
            "personality_type": "persuasive",
            "traits": ["charismatic", "influential", "rapport-builder", "manipulative", "win-win focused", "psychologically savvy"],
            "negotiation_style": (
                "Master of persuasion who uses charm, rapport-building, and psychological influence "
                "to create win-win scenarios. Employs storytelling, emotional appeal, and strategic "
                "compliments to guide negotiations favorably while ensuring profitable deals. "
                "Never goes below min_price."
            ),
            "catchphrases": [
                "I believe we can create a win-win situation here.",
                "These are premium and worth every rupee.",
                "You won't find this quality elsewhere.",
                "I've already come down a lot for you.",
                "Let's close this deal today.",
                "This is the best you'll get in the market."
            ]
        }

    # ---------- State helpers ----------
    def _init_state(self, context: NegotiationContext):
        if not hasattr(self, "_state"):
            self._state = {
                "buyer_history": [],
                "max_buyer_seen": None,
                "buyer_max_est": None,
                "concessions": {"buyer": [], "seller": []},
                "last_buyer_tone": "neutral",
            }

    def _format_professional(self, content: str) -> str:
        lead = random.choice(["Professionally:", "Let's be clear:", "For efficiency:", "Directly:"])
        tail = random.choice(["Confirm at your earliest.", "I expect reciprocity.", "Proceed accordingly.", "This is sustainable."])
        return f"{lead} {content} {tail}"

    # ---------- Tone analysis ----------
    def analyze_buyer_tone(self, text: str) -> str:
        if not text:
            return "neutral"
        t = text.lower()
        emotional = ["angry", "unfair", "frustrat", "demand", "unacceptable", "!", "urgent"]
        logical = ["market", "budget", "price", "analysis", "cost", "%", "data"]
        polite = ["please", "thank", "appreciate"]

        score = 0
        for kw in emotional:
            if kw in t: score -= 2
        for kw in logical: 
            if kw in t: score += 1
        for kw in polite:
            if kw in t: score += 1

        if score <= -1: return "emotional"
        if score >= 1: return "logical"
        return "neutral"

    def personality_adaptation(self, buyer_message: str) -> str:
        tone = self.analyze_buyer_tone(buyer_message)
        self._state["last_buyer_tone"] = tone
        if tone == "emotional":
            return "logical"
        if tone == "logical":
            return "appeal"
        return "logical"

    # ---------- Concession tracking ----------
    def _record_concession(self, actor: str, amount: int):
        self._state["concessions"][actor].append(amount)

    def _buyer_made_concession(self, new_buyer_price: int) -> Optional[int]:
        hist = self._state["buyer_history"]
        if not hist:
            return None
        last = hist[-1]
        if new_buyer_price > last:
            return new_buyer_price - last
        return None

    def _format_reciprocity_request(self, seller_concession_count: int) -> str:
        demands = [
            "commitment to higher volume",
            "faster payment terms",
            "exclusive supplier status",
            "priority contract renewal",
            "multi-order agreement"
        ]
        idx = min(len(demands) - 1, seller_concession_count - 1) if seller_concession_count > 0 else 0
        return demands[idx]

    # ---------- Pricing helpers ----------
    def _opening_offer_number(self, context: NegotiationContext) -> int:
        market = context.product.base_market_price
        opening = int(market * self.AGG_OPEN_RATIO)
        return max(opening, int(market * self.MARKET_OPEN_RATIO))

    def _walkaway_floor(self, context: NegotiationContext) -> int:
        market = context.product.base_market_price
        return int(market * self.WALKAWAY_RATIO)

    def _update_buyer_estimates(self, buyer_price: int):
        st = self._state
        st["buyer_history"].append(buyer_price)

        if st["max_buyer_seen"] is None:
            st["max_buyer_seen"] = buyer_price
        else:
            st["max_buyer_seen"] = max(st["max_buyer_seen"], buyer_price)

        rough_cap = int(buyer_price * 1.10)
        if st["buyer_max_est"] is None:
            st["buyer_max_est"] = rough_cap
        else:
            st["buyer_max_est"] = int(self.EST_DECAY * st["buyer_max_est"] + (1 - self.EST_DECAY) * rough_cap)

    def _closing_target_from_estimate(self, context: NegotiationContext) -> Optional[int]:
        st = self._state
        if not st["max_buyer_seen"]:
            return None
        est_cap = int(st["max_buyer_seen"] * 1.02)
        return est_cap

    # ---------- Required ----------
    def generate_opening_offer(self, context: NegotiationContext) -> Tuple[int, str]:
        self._init_state(context)
        offer = self._opening_offer_number(context)
        name = context.product.name
        qty = context.product.quantity
        content = f"My opening is ₹{offer} for {qty} units of {context.product.quality_grade}-grade {name}."
        self._record_concession("seller", 0)
        return offer, self._format_professional(content)

    def respond_to_seller_offer(self, context: NegotiationContext, buyer_price: int, buyer_message: str) -> Tuple[DealStatus, int, str]:
        self._init_state(context)

        if buyer_price:
            buyer_conc = self._buyer_made_concession(buyer_price) if self._state["buyer_history"] else None
            self._update_buyer_estimates(buyer_price)
            if buyer_conc and buyer_conc > 0:
                self._record_concession("buyer", buyer_conc)

        tone_adapt = self.personality_adaptation(buyer_message)

        market = context.product.base_market_price
        opening = self._opening_offer_number(context)
        floor = self._walkaway_floor(context)
        last_my = context.your_offers[-1] if context.your_offers else opening

        closing_target = self._closing_target_from_estimate(context)
        if closing_target is not None:
            closing_target = max(closing_target, floor)

        # Late-round finalization
        if context.current_round >= 9:
            if buyer_price and buyer_price >= floor:
                msg = f"Finalizing at ₹{buyer_price}."
                return DealStatus.ACCEPTED, buyer_price, self._format_professional(msg)
            last_shot = max(floor, market)
            if closing_target:
                last_shot = max(last_shot, closing_target)
            demand = self._format_reciprocity_request(len(self._state["concessions"]["seller"]))
            msg = f"Final offer ₹{last_shot}. In return I require: {demand}. Immediate confirmation secures the deal."
            return DealStatus.ONGOING, last_shot, self._format_professional(msg)

        # Dynamic target
        r = max(1, min(10, context.current_round))
        progress = (r - 1) / 9.0
        eased = progress ** 0.9
        dynamic_target = int(opening - (opening - floor) * eased)

        if buyer_price and buyer_price >= dynamic_target:
            msg = f"Agreed at ₹{buyer_price}. Efficient resolution."
            return DealStatus.ACCEPTED, buyer_price, self._format_professional(msg)

        # Calculate counter
        gap = (last_my - buyer_price) if buyer_price else 0
        step = int(max(self.MIN_STEP, market * 0.05))

        if r > self.FAST_CONCESSION_AFTER:
            step = int(step * self.FAST_CONCESSION_MULT)

        proposed = max(last_my - step, floor)

        # Record seller concession
        if proposed < last_my:
            self._record_concession("seller", last_my - proposed)

        # Reciprocity check
        buyer_conc_count = len(self._state["concessions"]["buyer"])
        seller_conc_count = len(self._state["concessions"]["seller"])
        reciprocity_text = ""
        if seller_conc_count > buyer_conc_count:
            reciprocity_text = f" In return I require: {self._format_reciprocity_request(seller_conc_count)}."

        if tone_adapt == "logical":
            content = f"My counter is ₹{proposed}. This reflects market floor and sustainable pricing." + reciprocity_text
        else:
            content = f"My counter is ₹{proposed}. I’d prefer to continue this partnership — include {self._format_reciprocity_request(seller_conc_count)}, and we close today."

        return DealStatus.ONGOING, proposed, self._format_professional(content)
    def get_personality_prompt(self) -> str:
        return (
            "You are a master of persuasion and influence in sales negotiations. You use charm, "
            "rapport-building, and psychological techniques to create win-win scenarios. "
            "You frequently emphasize quality, value, and exclusivity. You use phrases "
            "like 'premium quality,' 'you won't find this elsewhere,' and 'let's create a partnership.' "
            "You're charismatic, emotionally intelligent, and skilled at making buyers feel "
            "they're getting exceptional value while maintaining profitable pricing."
        )


# ============================================
# PART 4: EXAMPLE SIMPLE AGENT (FOR REFERENCE)
# ============================================

class ExampleSimpleAgent(BaseBuyerAgent):
    """
    A simple example agent that you can use as reference.
    This agent has basic logic - you should do better!
    """
    
    def define_personality(self) -> Dict[str, Any]:
        return {
            "personality_type": "cautious",
            "traits": ["careful", "budget-conscious", "polite"],
            "negotiation_style": "Makes small incremental offers, very careful with money",
            "catchphrases": ["Let me think about that...", "That's a bit steep for me"]
        }
    
    def generate_opening_offer(self, context: NegotiationContext) -> Tuple[int, str]:
        # Start at 60% of market price
        opening = int(context.product.base_market_price * 0.6)
        opening = min(opening, context.your_budget)
        
        return opening, f"I'm interested, but ₹{opening} is what I can offer. Let me think about that..."
    
    def respond_to_seller_offer(self, context: NegotiationContext, seller_price: int, seller_message: str) -> Tuple[DealStatus, int, str]:
        # Accept if within budget and below 85% of market
        if seller_price <= context.your_budget and seller_price <= context.product.base_market_price * 0.85:
            return DealStatus.ACCEPTED, seller_price, f"Alright, ₹{seller_price} works for me!"
        
        # Counter with small increment
        last_offer = context.your_offers[-1] if context.your_offers else 0
        counter = min(int(last_offer * 1.1), context.your_budget)
        
        if counter >= seller_price * 0.95:  # Close to agreement
            counter = min(seller_price - 1000, context.your_budget)
            return DealStatus.ONGOING, counter, f"That's a bit steep for me. How about ₹{counter}?"
        
        return DealStatus.ONGOING, counter, f"I can go up to ₹{counter}, but that's pushing my budget."
    
    def get_personality_prompt(self) -> str:
        return """
        I am a cautious buyer who is very careful with money. I speak politely but firmly.
        I often say things like 'Let me think about that' or 'That's a bit steep for me'.
        I make small incremental offers and show concern about my budget.
        """


# ============================================
# PART 5: TESTING FRAMEWORK (DO NOT MODIFY)
# ============================================

class MockSellerAgent:
    """A simple mock seller for testing your agent"""
    
    def __init__(self, min_price: int, personality: str = "standard"):
        self.min_price = min_price
        self.personality = personality
        
    def get_opening_price(self, product: Product) -> Tuple[int, str]:
        # Start at 150% of market price
        price = int(product.base_market_price * 1.5)
        return price, f"These are premium {product.quality_grade} grade {product.name}. I'm asking ₹{price}."
    
    def respond_to_buyer(self, buyer_offer: int, round_num: int) -> Tuple[int, str, bool]:
        if buyer_offer >= self.min_price * 1.1:  # Good profit
            return buyer_offer, f"You have a deal at ₹{buyer_offer}!", True
            
        if round_num >= 8:  # Close to timeout
            counter = max(self.min_price, int(buyer_offer * 1.05))
            return counter, f"Final offer: ₹{counter}. Take it or leave it.", False
        else:
            counter = max(self.min_price, int(buyer_offer * 1.15))
            return counter, f"I can come down to ₹{counter}.", False


def run_negotiation_test(buyer_agent: BaseBuyerAgent, product: Product, buyer_budget: int, seller_min: int) -> Dict[str, Any]:
    """Test a negotiation between your buyer and a mock seller"""
    
    seller = MockSellerAgent(seller_min)
    context = NegotiationContext(
        product=product,
        your_budget=buyer_budget,
        current_round=0,
        seller_offers=[],
        your_offers=[],
        messages=[]
    )
    
    # Seller opens
    seller_price, seller_msg = seller.get_opening_price(product)
    context.seller_offers.append(seller_price)
    context.messages.append({"role": "seller", "message": seller_msg})
    
    # Run negotiation
    deal_made = False
    final_price = None
    
    for round_num in range(10):  # Max 10 rounds
        context.current_round = round_num + 1
        
        # Buyer responds
        if round_num == 0:
            buyer_offer, buyer_msg = buyer_agent.generate_opening_offer(context)
            status = DealStatus.ONGOING
        else:
            status, buyer_offer, buyer_msg = buyer_agent.respond_to_seller_offer(
                context, seller_price, seller_msg
            )
        
        context.your_offers.append(buyer_offer)
        context.messages.append({"role": "buyer", "message": buyer_msg})
        
        if status == DealStatus.ACCEPTED:
            deal_made = True
            final_price = seller_price
            break
            
        # Seller responds
        seller_price, seller_msg, seller_accepts = seller.respond_to_buyer(buyer_offer, round_num)
        
        if seller_accepts:
            deal_made = True
            final_price = buyer_offer
            context.messages.append({"role": "seller", "message": seller_msg})
            break
            
        context.seller_offers.append(seller_price)
        context.messages.append({"role": "seller", "message": seller_msg})
    
    # Calculate results
    result = {
        "deal_made": deal_made,
        "final_price": final_price,
        "rounds": context.current_round,
        "savings": buyer_budget - final_price if deal_made else 0,
        "savings_pct": ((buyer_budget - final_price) / buyer_budget * 100) if deal_made else 0,
        "below_market_pct": ((product.base_market_price - final_price) / product.base_market_price * 100) if deal_made else 0,
        "conversation": context.messages
    }
    
    return result


# ============================================
# PART 6: TEST YOUR AGENT
# ============================================

def test_buyer_agent():
    """Run this to test your agent implementation"""
    
    # Create test products
    test_products = [
        Product(
            name="Alphonso Mangoes",
            category="Mangoes",
            quantity=100,
            quality_grade="A",
            origin="Ratnagiri",
            base_market_price=180000,
            attributes={"ripeness": "optimal", "export_grade": True}
        ),
        Product(
            name="Kesar Mangoes", 
            category="Mangoes",
            quantity=150,
            quality_grade="B",
            origin="Gujarat",
            base_market_price=150000,
            attributes={"ripeness": "semi-ripe", "export_grade": False}
        )
    ]
    
    # Initialize your agent
    your_agent = YourBuyerAgent("TestBuyer")
    
    print("="*60)
    print(f"TESTING YOUR AGENT: {your_agent.name}")
    print(f"Personality: {your_agent.personality['personality_type']}")
    print("="*60)
    
    total_savings = 0
    deals_made = 0
    
    # Run multiple test scenarios
    for product in test_products:
        for scenario in ["easy", "medium", "hard"]:
            if scenario == "easy":
                buyer_budget = int(product.base_market_price * 1.2)
                seller_min = int(product.base_market_price * 0.8)
            elif scenario == "medium":
                buyer_budget = int(product.base_market_price * 1.0)
                seller_min = int(product.base_market_price * 0.85)
            else:  # hard
                buyer_budget = int(product.base_market_price * 0.9)
                seller_min = int(product.base_market_price * 0.82)
            
            print(f"\nTest: {product.name} - {scenario} scenario")
            print(f"Your Budget: ₹{buyer_budget:,} | Market Price: ₹{product.base_market_price:,}")
            
            result = run_negotiation_test(your_agent, product, buyer_budget, seller_min)
            
            if result["deal_made"]:
                deals_made += 1
                total_savings += result["savings"]
                print(f"✅ DEAL at ₹{result['final_price']:,} in {result['rounds']} rounds")
                print(f"   Savings: ₹{result['savings']:,} ({result['savings_pct']:.1f}%)")
                print(f"   Below Market: {result['below_market_pct']:.1f}%")
            else:
                print(f"❌ NO DEAL after {result['rounds']} rounds")
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print(f"Deals Completed: {deals_made}/6")
    print(f"Total Savings: ₹{total_savings:,}")
    print(f"Success Rate: {deals_made/6*100:.1f}%")
    print("="*60)

def test_seller_agent():
    """Run this to test your Seller Agent implementation"""

    # Create test products
    test_products = [
        Product(
            name="Alphonso Mangoes",
            category="Mangoes",
            quantity=100,
            quality_grade="A",
            origin="Ratnagiri",
            base_market_price=180000,
            attributes={"ripeness": "optimal", "export_grade": True}
        ),
        Product(
            name="Kesar Mangoes",
            category="Mangoes",
            quantity=150,
            quality_grade="B",
            origin="Gujarat",
            base_market_price=150000,
            attributes={"ripeness": "semi-ripe", "export_grade": False}
        )
    ]

    # Initialize your seller agent
    seller_agent = YourSellerAgent("TestSeller")

    print("=" * 60)
    print(f"TESTING YOUR SELLER AGENT: {seller_agent.name}")
    print(f"Personality: {seller_agent.personality['personality_type']}")
    print("=" * 60)

    total_profit = 0
    deals_made = 0

    # Run multiple test scenarios
    for product in test_products:
        for scenario in ["easy", "medium", "hard", "very_hard", "budget_tight", "seller_strong"]:
            if scenario == "easy":
                buyer_budget = int(product.base_market_price * 1.2)   # Buyer has plenty of money
                seller_min   = int(product.base_market_price * 0.8)
            elif scenario == "medium":
                buyer_budget = int(product.base_market_price * 1.0)   # Buyer at market price
                seller_min   = int(product.base_market_price * 0.85)
            elif scenario == "hard":
                buyer_budget = int(product.base_market_price * 0.9)   # Buyer below market
                seller_min   = int(product.base_market_price * 0.82)
            elif scenario == "very_hard":
                buyer_budget = int(product.base_market_price * 0.85)  # Buyer very tight
                seller_min   = int(product.base_market_price * 0.90)  # Seller above market
            elif scenario == "budget_tight":
                buyer_budget = int(product.base_market_price * 0.8)   # Buyer extremely low
                seller_min   = int(product.base_market_price * 0.75)  # Seller floor lower
            elif scenario == "seller_strong":
                buyer_budget = int(product.base_market_price * 1.05)  # Buyer has some room
                seller_min   = int(product.base_market_price * 0.95)  # Seller barely negotiates


            print(f"\nTest: {product.name} - {scenario} scenario")
            print(f"Buyer Budget: ₹{buyer_budget:,} | Market Price: ₹{product.base_market_price:,} | Seller Floor: ₹{seller_min:,}")

            result = run_negotiation_test(seller_agent, product, buyer_budget, seller_min)

            if result["deal_made"]:
                deals_made += 1
                profit = result["final_price"] - product.base_market_price
                total_profit += profit
                above_market_pct = (profit / product.base_market_price * 100) if product.base_market_price > 0 else 0

                print(f"✅ DEAL at ₹{result['final_price']:,} in {result['rounds']} rounds")
                print(f"   Profit vs Market: ₹{profit:,} ({above_market_pct:.1f}% above market)")
            else:
                print(f"❌ NO DEAL after {result['rounds']} rounds")


    # Summary
    print("\n" + "=" * 60)
    print("SELLER SUMMARY")
    print(f"Deals Completed: {deals_made}/6")
    print(f"Total Extra Profit: ₹{total_profit:,}")
    print(f"Success Rate: {deals_made/6*100:.1f}%")
    print("=" * 60)




# ============================================
# PART 7: EVALUATION CRITERIA
# ============================================

"""
YOUR SUBMISSION WILL BE EVALUATED ON:

1. **Deal Success Rate (30%)**
   - How often you successfully close deals
   - Avoiding timeouts and failed negotiations

2. **Savings Achieved (30%)**
   - Average discount from seller's opening price
   - Performance relative to market price

3. **Character Consistency (20%)**
   - How well you maintain your chosen personality
   - Appropriate use of catchphrases and style

4. **Code Quality (20%)**
   - Clean, well-structured implementation
   - Good use of helper methods
   - Clear documentation

BONUS POINTS FOR:
- Creative, unique personalities
- Sophisticated negotiation strategies
- Excellent adaptation to different scenarios
"""

# ============================================
# PART 8: SUBMISSION CHECKLIST
# ============================================

"""
BEFORE SUBMITTING, ENSURE:

[ ] Your agent is fully implemented in YourBuyerAgent class
[ ] You've defined a clear, consistent personality
[ ] Your agent NEVER exceeds its budget
[ ] You've tested using test_your_agent()
[ ] You've added helpful comments explaining your strategy
[ ] You've included any additional helper methods

SUBMIT:
1. This completed template file
2. A 1-page document explaining:
   - Your chosen personality and why
   - Your negotiation strategy
   - Key insights from testing

FILENAME: negotiation_agent_[your_name].py
"""

if __name__ == "__main__":
    test_buyer_agent()
    test_seller_agent()
