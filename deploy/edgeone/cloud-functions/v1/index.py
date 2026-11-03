"""EdgeOne removes /v1 before forwarding to the Flask application."""
from flask import Flask
from articheck.edgeone_review import create_app

# The explicit Flask entry flag is required by EdgeOne's Python route scanner.
app = Flask(__name__)
app = create_app()
