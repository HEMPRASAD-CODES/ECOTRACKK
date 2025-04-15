from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user
import joblib
from twilio.rest import Client
from datetime import datetime
from flask_mail import Mail, Message
import threading
import random
import os
import dotenv
from dotenv import load_dotenv
from flask import Flask, redirect, request, session, url_for, render_template
from google_auth_oauthlib.flow import Flow
import os
import requests
import json
from flask_cors import CORS
from flask_session import Session
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import time
import logging
import csv
from flask_cors import CORS
import pandas as pd
import folium
from geopy.distance import geodesic
from polyline import decode
from scipy.interpolate import interp1d
import numpy as np
from math import radians, cos, sin, sqrt,atan2

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
app.secret_key = 'achp-2005-'  # Ensure this is secure
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://sql12773326:KGWALbzQpP@sql12.freesqldatabase.com:3306/sql12773326'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key'

# Initialize extensions
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ... rest of your code ... 

# Register Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            phone_number = request.form.get('phone_number')

            # Validate required fields
            if not all([username, email, password, phone_number]):
                flash('All fields are required', 'danger')
                return redirect(url_for('register'))

            # Check if user already exists
            existing_user = UserData.query.filter_by(email=email).first()
            if existing_user:
                flash('Email already registered', 'danger')
                return redirect(url_for('register'))

            # Create new user
            new_user = UserData(
                username=username,
                email=email,
                password=password,  # Note: In production, you should hash the password
                phone_number=phone_number,
                points=0,
                badge="Beginner",
                is_admin=False
            )

            # Add to database
            db.session.add(new_user)
            db.session.commit()

            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            db.session.rollback()
            flash(f'Registration failed: {str(e)}', 'danger')
            logging.error(f"Registration error: {str(e)}")
            return redirect(url_for('register'))

    return render_template('register.html')

# Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            email = request.form.get('email')
            password = request.form.get('password')

            user = UserData.query.filter_by(email=email).first()

            if user and user.password == password:  # Note: In production, use password hashing
                login_user(user)
                flash('Login successful!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Invalid email or password', 'danger')

        except Exception as e:
            flash(f'Login failed: {str(e)}', 'danger')
            logging.error(f"Login error: {str(e)}")

    return render_template('login.html') 
