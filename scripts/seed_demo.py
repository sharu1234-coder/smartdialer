#!/usr/bin/env python3
"""Seed the database with demo data for manual testing."""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, create_all_tables
from app.repositories.campaign_repository import create_campaign, update_campaign_status
from app.repositories.agent_repository import create_agent
from app.repositories.borrower_repository import create_borrower
from app.core.enums import CampaignStatus, DialMode


def seed_demo():
    create_all_tables()
    db = next(get_db())
    try:
        print("Seeding demo data...")

        # Progressive campaign
        camp_p = create_campaign(db, "Demo Progressive Campaign", DialMode.PROGRESSIVE, 50)
        update_campaign_status(db, camp_p.id, CampaignStatus.ACTIVE)

        for i in range(10):
            create_agent(db, f"Agent-Progressive-{i+1:02d}", campaign_id=camp_p.id)

        for i in range(100):
            create_borrower(db, campaign_id=camp_p.id,
                            phone_number=f"+1555{i:07d}",
                            name=f"Customer {i+1}",
                            priority=i % 5)

        # Predictive campaign
        camp_pred = create_campaign(db, "Demo Predictive Campaign", DialMode.PREDICTIVE, 50)
        update_campaign_status(db, camp_pred.id, CampaignStatus.ACTIVE)

        for i in range(10):
            create_agent(db, f"Agent-Predictive-{i+1:02d}", campaign_id=camp_pred.id)

        for i in range(100):
            create_borrower(db, campaign_id=camp_pred.id,
                            phone_number=f"+1444{i:07d}",
                            name=f"Lead {i+1}",
                            priority=i % 5)

        db.commit()

        print(f"Created progressive campaign: {camp_p.id}")
        print(f"Created predictive campaign: {camp_pred.id}")
        print("Done — 20 agents, 200 borrowers seeded.")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo()
