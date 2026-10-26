"""Invoke the local application without implicit services or environment edits."""
from .app import main

raise SystemExit(main())
