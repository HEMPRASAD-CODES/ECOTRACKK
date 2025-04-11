from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user
from twilio.rest import Client
from datetime import datetime
from flask_mail import Mail, Message
import threading
import random
import os
import dotenv
from dotenv import load_dotenv

app = Flask(__name__)
# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+mysqlconnector://root:Achp-2005-@localhost/sustainability_db'
app.config['SECRET_KEY'] = 'your_secret_key'
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.Text, nullable=False)
    phone_number = db.Column(db.String(15))  # Changed to String for consistency
    points = db.Column(db.Integer, default=0)
    badge = db.Column(db.String(50), default="Beginner")
    is_admin = db.Column(db.Boolean, default=False)

class Orphanage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    contact_number = db.Column(db.String(15), nullable=False)

class FoodDonation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    orphanage_id = db.Column(db.Integer, db.ForeignKey('orphanage.id'), nullable=False)
    food_type = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    pickup_time = db.Column(db.DateTime, nullable=False)
    pickup_place = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='Scheduled')
class ParkingLot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    total_bike_slots = db.Column(db.Integer, default=500)
    total_car_slots = db.Column(db.Integer, default=200)
    slots = db.relationship('ParkingSlot', backref='parking_lot', lazy=True)

class ParkingSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lot_id = db.Column(db.Integer, db.ForeignKey('parking_lot.id'), nullable=False)
    slot_type = db.Column(db.String(10), nullable=False)  # 'Bike' or 'Car'
    status = db.Column(db.String(10), default='Vacant')  # 'Occupied' or 'Vacant'
    current_user = db.Column(db.String(100), nullable=True)
    allotted_time = db.Column(db.Time, nullable=True)
    expiry_time = db.Column(db.Time, nullable=True)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('parking_slot.id'), nullable=False)
    booking_date = db.Column(db.Date, nullable=False)  # New field for booking date
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), default='Active')  # 'Active' or 'Completed'
    otp = db.Column(db.Integer)
@app.route('/api/parking_lots', methods=['GET'])
def get_parking_lots():
    lots = ParkingLot.query.all()
    return jsonify([{'id': lot.id, 'name': lot.name, 'total_bike_slots': lot.total_bike_slots, 'total_car_slots': lot.total_car_slots} for lot in lots])

@app.route('/api/parking_slots/<int:lot_id>', methods=['GET'])
def get_parking_slots(lot_id):
    # Fetch all slots for the given parking lot
    slots = ParkingSlot.query.filter_by(lot_id=lot_id).all()

    # Filter for least numbered bike and car slots
    bike_slot = min((slot for slot in slots if slot.slot_type == 'Bike' and slot.status == 'Vacant'), 
                    key=lambda x: x.id, default=None)
    car_slot = min((slot for slot in slots if slot.slot_type == 'Car' and slot.status == 'Vacant'), 
                   key=lambda x: x.id, default=None)

    # Prepare the response
    response = []
    if bike_slot:
        response.append({'id': bike_slot.id, 'slot_type': bike_slot.slot_type, 'status': bike_slot.status})
    if car_slot:
        response.append({'id': car_slot.id, 'slot_type': car_slot.slot_type, 'status': car_slot.status})

    return jsonify(response)
@app.route('/api/book_slot', methods=['POST'])
@login_required
def book_slot():
    data = request.json
    slot_id = data['slot_id']
    booking_date = data['booking_date']  # Get the booking date from the request
    start_time = data['start_time']
    end_time = data['end_time']

    slot = ParkingSlot.query.get(slot_id)
    if slot and slot.status == 'Vacant':
        slot.status = 'Occupied'
        slot.current_user = current_user.username
        slot.allotted_time = start_time
        slot.expiry_time = end_time

        # Generate a 6-digit OTP
        otp = generate_unique_otp()
        
        send_sms(current_user.phone_number, f"Your OTP for parking slot booking on {booking_date} between {start_time} and {end_time} is: {otp}")
        booking = Booking(user_id=current_user.id, slot_id=slot_id, booking_date=booking_date, start_time=start_time, end_time=end_time, otp=otp)
        db.session.add(booking)
        db.session.commit()

        return jsonify({'message': 'Slot booked successfully!', 'otp': otp}), 201
    return jsonify({'message': 'Slot is not available.'}), 400
def generate_unique_otp():
    while True:
        otp = str(random.randint(100000, 999999))  # Generate a 6-digit OTP
        if not Booking.query.filter_by(otp=otp).first():  # Check if OTP already exists
            return otp  # Return unique OTP

@app.route('/api/verify_otp', methods=['POST'])
@login_required
def verify_otp():
    data = request.json
    otp = data['otp']
    otp = int(otp)  # Convert received OTP to integer
    print(f"Received OTP: {otp} (type: {type(otp)})")

    # Find all active bookings for the current user
    bookings = Booking.query.filter_by(status='Active').all()

    # Check if any booking matches the provided OTP
    for booking in bookings:
        print(f"Checking booking with OTP: {booking.otp} (type: {type(booking.otp)}) against {otp}")
        if str(booking.otp).strip() == str(otp).strip():            # Return the booking and slot details
            return jsonify({
                'message': 'OTP verified successfully!',
                'booking_details': {
                    'slot_id': booking.id,
                    'status': booking.status,
                    'allotted_time': str(booking.start_time),
                    'expiry_time': str(booking.end_time),
                    'otp': booking.otp  # Include OTP for reference
                }
            }), 200

    # If no matching OTP was found
    return jsonify({'message': 'Invalid OTP. No active booking found with this OTP.'}), 400
@app.route('/api/release_slot', methods=['POST'])
@login_required
def release_slot():
    data = request.json
    slot_id = data['slot_id']

    slot = ParkingSlot.query.get(slot_id)
    if slot and slot.current_user == current_user.username:
        slot.status = 'Vacant'
        slot.current_user = None
        slot.allotted_time = None
        slot.expiry_time = None
        slot.otp = None  # Clear the OTP when the slot is released

        booking = Booking.query.filter_by(slot_id=slot_id, user_id=current_user.id, status='Active').first()
        if booking:
            booking.status = 'Completed'

        db.session.commit()
        return jsonify({'message': 'Slot released successfully!'}), 200
    return jsonify({'message': 'You do not have permission to release this slot.'}), 403

def auto_release_slots():
    with app.app_context():  # Create an application context
        while True:
            current_time = datetime.now().time()
            # Find all active bookings that have expired
            expired_bookings = Booking.query.filter(
                Booking.end_time < current_time,
                Booking.status == 'Active'
            ).all()

            for booking in expired_bookings:
                # Find the corresponding parking slot
                slot = ParkingSlot.query.get(booking.slot_id)
                if slot:
                    # Update the slot to be available
                    slot.status = 'Vacant'
                    slot.current_user = None
                    slot.allotted_time = None
                    slot.expiry_time = None

                    # Update the booking status to 'Inactive' or 'Completed'
                    booking.status = 'Completed'  # or 'Inactive' based on your requirement

            db.session.commit()  # Commit all changes to the database
            time.sleep(60)  # Check every minute
REWARDS = {
    100: "Congratulations! You've earned a 10% Discount on your next purchase at Vmart!"
    "Contact us through this website for the coupon code ",
    200: "Awesome! You've earned a free coffee voucher at GymKhana!"
    "Contact us through this website for the coupon code ",
    500: "Fantastic! You've earned a gift card worth Rs.1000!"
    "Contact us through this website for the coupon code ",
    1000: "Incredible! You've earned a premium membership at the University Gym for a month!"
    "Contact us through this website for the coupon code "
}

@app.route('/rewards', methods=['GET'])
@login_required
def rewards():
    # Get the current user's XP
    current_xp = current_user.points  # Assuming points is the XP field

    # Determine rewards based on current XP
    user_rewards = []
    highest=None
    for threshold, reward in sorted(REWARDS.items()):
        if current_xp >= threshold:
            highest=reward
            
    user_rewards.append(highest)
    return render_template('rewards.html', current_xp=current_xp, user_rewards=user_rewards)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        admin = User.query.filter_by(email=email, is_admin=True).first()

        if not admin:
            flash('Error: No admin account found with this email.', 'danger')
        else:
            if admin.password != password:  # Direct comparison for plain text
                flash('Error: Incorrect password. Please try again.', 'danger')
            else:
                login_user(admin)
                flash('Admin login successful!', 'success')
                return redirect(url_for('admin_dashboard'))

    return render_template('admin_login.html')

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('index'))

    users = User.query.all()  # Get all users
    return render_template('admin_dashboard.html', users=users)

import getpass
from flask.cli import AppGroup

cli = AppGroup('admin')

@cli.command("create_admin")
def create_admin():
    username = input("Enter Admin's name:")
    email = input("Enter admin email: ")
    password = input("Enter admin password: ")  # No hashing
    user = User(username=username, email=email, password=password, is_admin=True)
    db.session.add(user)
    db.session.commit()
    print(f"Admin user {email} created successfully!")

# Authenticating a user
app.cli.add_command(cli)

def validate_email(email):
    return "@" in email and "." in email

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Home Route
@app.route('/')
def home():
    return render_template('dashboard.html')

# Register Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        phone_number = request.form['phone_number']

        user = User(username=username, email=email, password=password, phone_number=phone_number)
        db.session.add(user)
        db.session.commit()

        flash('Registration Successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

# Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if not user:
            flash('Error: No account found with this email.', 'danger')
        elif user.password != password:
            flash('Error: Incorrect password. Please try again.', 'danger')
        else:
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('index'))

    return render_template('login.html')

@app.route('/about', methods=['GET', 'POST'])
def about():
    return render_template('about.html')
@app.route('/admin/parking', methods=['GET', 'POST'])
def parking():
    return render_template('parking.html')
@app.route('/index', methods=['GET', 'POST'])
@login_required
def index():
    return render_template('index.html', username=current_user.username, points=current_user.points, badge=current_user.badge)

@app.route('/initiatives')
def initiatives():
    return render_template('initiatives.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    return render_template('contact.html')

@app.route('/events', methods=['GET', 'POST'])
def events():
    return render_template('events.html')

@app.route('/faq', methods=['GET', 'POST'])
def faq():
    return render_template('faq.html')

@app.route('/food-donation', methods=['GET', 'POST'])
def food_donation():
    return render_template('food-donation.html')

@app.route('/blood-donation', methods=['GET', 'POST'])
def blood_donation():
    return render_template('blood-donation.html')

@app.route('/food-wastage', methods=['GET', 'POST'])
def food_wastage():
    return render_template('food-wastage.html')

@app.route('/gallery', methods=['GET', 'POST'])
def gallery():
    return render_template('gallery.html')

@app.route('/outmap', methods=['GET', 'POST'])
def outmap():
    return render_template('route_map.html')

@app.route('/ecoroute', methods=['GET', 'POST'])
def ecoroute():
    return render_template('idummy.html')

@app.route('/water-resource', methods=['GET', 'POST'])
def water_resource():
    return render_template('water-resource.html')

# Dashboard Route
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', username=current_user.username, points=current_user.points, badge=current_user.badge)

# Orphanage API
@app.route('/api/orphanages', methods=['GET'])
def get_orphanages():
    orphanages = Orphanage.query.all()
    return jsonify([{'id': o.id, 'name': o.name, 'address': o.address} for o in orphanages])

# Food Donation API
@app.route('/api/donate_food', methods=['POST'])
@login_required
def donate_food():
    data = request.json
    food_donation = FoodDonation(
        user_id=current_user.id,
        orphanage_id=data['orphanage_id'],
        food_type=data['food_type'],
        quantity=data['quantity'],
        pickup_time=datetime.fromisoformat(data['pickup_time']),
        pickup_place=data['pickup_place']
    )
    db.session.add(food_donation)
    db.session.commit()

    # Add 10 XP to the user's account
    current_user.points += 10
    db.session.commit()  # Commit the changes to the database

    # Notify donor and orphanage
    notify_orphanage(food_donation)

    return jsonify({
        'message': 'Donation scheduled successfully! You have earned 10 XP.',
        'food_type': food_donation.food_type,
        'quantity': food_donation.quantity
    }), 201

# Twilio Configuration
TWILIO_ACCOUNT_SID = 'AC1e23a4a5289b9eef5e23eb51f03b8792'
TWILIO_AUTH_TOKEN = 'eb99e476c932a8e1cefd3b33e8c33207'
TWILIO_PHONE_NUMBER = '+13306425776'

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Models for Blood Donation
class BloodDonor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blood_type = db.Column(db.String(5), nullable=False)  # e.g., A+, O-, etc.
    phone_number = db.Column(db.String(15), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    is_available = db.Column(db.Boolean, default=True)

class BloodRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blood_type = db.Column(db.String(5), nullable=False)
    urgency = db.Column(db.String(20), nullable=False)  # e.g., Critical, Normal
    location = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='Pending')  # Pending, Matched, Completed

# API to Request Blood
@app.route('/api/register_donor', methods=['POST'])
@login_required
def register_donor():
    data = request.json
    donor = BloodDonor(
        user_id=current_user.id,
        blood_type=data['blood_type'],
        phone_number=data['contact'],
        location=data['location'],
        is_available=data['availability'] == 'Available'
    )
    db.session.add(donor)
    db.session.commit()

    # Check for matching blood requests
    matching_requests = BloodRequest.query.filter_by(blood_type=data['blood_type'], status='Pending').all()

    if matching_requests:
        for req in matching_requests:
            message = f"A Blood Donation Request for your Blood Group {req.blood_type} at {req.location} with emergency level {req.urgency}."
            send_sms(current_user.phone_number, message)
            current_user.points += 25
            db.session.commit()
            return jsonify({'message': message}), 200
    else:
        return jsonify({'message': 'No Immediate Requests Found. If found, SMS will be sent to notify you.'}), 200

# API to Request Blood
@app.route('/api/request_blood', methods=['POST'])
@login_required
def request_blood():
    data = request.json
    blood_request = BloodRequest(
        user_id=current_user.id,
        blood_type=data['blood_type'],
        urgency=data['urgency'],
        location=data['hospital']
    )
    db.session.add(blood_request)
    db.session.commit()

    # Try finding a matching donor
    matching_donors = BloodDonor.query.filter_by(blood_type=data['blood_type'], is_available=True).all()
    
    if matching_donors:
        # Notify the first available donor
        donor = matching_donors[0]  # Get the first matching donor
        send_sms(donor.phone_number, f"Match Found for your Blood Group {data['blood_type']} at {data['hospital']}.")

        # Award 25 XP points to the donor
        donor_user = User.query.get(donor.user_id)  # Get the donor's user object
        donor_user.points += 25
        db.session.commit()  # Commit the changes to the database

        return jsonify({'message': 'Match Found. SMS will be sent to the donor to notify him. The donor has earned 25 XP points!'}), 200

    return jsonify({'message': 'No Immediate donor Found. If found, SMS will be sent to notify you.'}), 200

def send_sms(to, message):
    client.messages.create(
        body=message,
        from_=TWILIO_PHONE_NUMBER,
        to=to
    )

def notify_orphanage(food_donation):
    orphanage = db.session.get(Orphanage, food_donation.orphanage_id)

    message = f"Hello, you have a new food donation scheduled. {food_donation.quantity} kg of {food_donation.food_type} will be picked up from {food_donation.pickup_place} on {food_donation.pickup_time}."
    client.messages.create(
        body=message,
        from_=TWILIO_PHONE_NUMBER,
        to=orphanage.contact_number
    )
from flask_login import logout_user

@app.route('/logout')
@login_required
def logout():
    logout_user()  # Log the user out
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('login'))  # Redirect to the login page
class ContactFormSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
@app.route('/save_contact', methods=['POST'])
def save_contact():
    data = request.json
    name = data.get('name')
    email = data.get('email')
    subject = data.get('subject')
    message = data.get('message')

    # Create a new contact form submission
    contact_submission = ContactFormSubmission(
        name=name,
        email=email,
        subject=subject,
        message=message
    )
    
    try:
        db.session.add(contact_submission)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Contact form submitted successfully!'}), 201
    except Exception as e:
        db.session.rollback()  # Rollback the session in case of error
        return jsonify({'status': 'error', 'message': str(e)}), 500
# API Keys
TOMTOM_API_KEY = "GGAOmaFE3JdavZQ8NbKbjAYqP8X6dHlX"
WEATHERBIT_API_KEY = "1122f550d34f4b33a862db4ea40d3e66"

# Function to get coordinates using geopy
def get_coordinates(city_name):
    geolocator = Nominatim(user_agent="city_route_locator")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
    location = geocode(city_name)
    if location:
        return location.latitude, location.longitude
    else:
        print(f"City '{city_name}' not found.")
        return None

# Function to predict CO2 emissions
def predict_co2_emissions(num_gears, transmission_type, engine_size, fuel_type, cylinders, fuel_consumption_comb):
    loaded_model = joblib.load('C:/Users/hempr/Downloads/fedex-main (5)/fedex-main (4)/fedex-main/fedex-main/model_final.pkl')

    transmission_type_mapping = {'A': 0, 'AM': 1, 'AS': 2, 'AV': 3, 'M': 4}
    fuel_type_mapping = {'D': 0, 'E': 1, 'N': 2, 'X': 3, 'Z': 4}

    transmission_type_encoded = transmission_type_mapping.get(transmission_type)
    fuel_type_encoded = fuel_type_mapping.get(fuel_type)

    input_data = [[num_gears, transmission_type_encoded, engine_size, fuel_type_encoded, cylinders, fuel_consumption_comb]]
    input_data = pd.DataFrame(input_data, columns=['Number of Gears', 'Transmission Type', 'Engine Size', 'Fuel Type', 'Cylinders', 'Fuel Consumption Comb'])

    prediction = loaded_model.predict(input_data)
    print("Predicted CO2 Emissions:", prediction[0])
    return prediction[0]

# Function to get weather data
def get_weather_data(coords, retries=5, delay=1):
    weather_url = "https://api.weatherbit.io/v2.0/forecast/daily"
    params = {
        "lat": coords[0],
        "lon": coords[1],
        "key": WEATHERBIT_API_KEY,
        "days": 1
    }

    for attempt in range(retries):
        try:
            response = requests.get(weather_url, params=params)
            response.raise_for_status()
            data = response.json()
            if "data" in data:
                weather_info = []
                for forecast in data["data"]:
                    timestamp = forecast["datetime"]
                    temperature = forecast["temp"]
                    rain = forecast.get("precip", 0)
                    rain_percentage = (rain / 10) * 100
                    weather_info.append({
                        "timestamp": timestamp,
                        "temperature": temperature,
                        "rain_percentage": rain_percentage
                    })
                return weather_info
            else:
                print("No weather data found.")
                return None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print(f"Rate limited. Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= 2
            else:
                print(f"Error fetching weather data: {e}")
                return None

weather_cache = {}

def get_weather_data_cached(coords):
    if coords in weather_cache:
        return weather_cache[coords]

    weather_data = get_weather_data(coords)
    weather_cache[coords] = weather_data
    return weather_data
from math import e
import webbrowser
import json
import requests
import folium
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from polyline import decode
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from geopy.distance import geodesic
import joblib


# Replace with your API keys
TOMTOM_API_KEY = "GGAOmaFE3JdavZQ8NbKbjAYqP8X6dHlX"
WEATHERBIT_API_KEY = "1122f550d34f4b33a862db4ea40d3e66"

# Function to get coordinates using geopy
def get_coordinates(city_name):
    geolocator = Nominatim(user_agent="city_route_locator")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
    location = geocode(city_name)
    if location:
        return location.latitude, location.longitude
    else:
        print(f"City '{city_name}' not found.")
        return None

# Function to get weather forecast for coordinates using Weatherbit API
import time


def predict_co2_emissions(num_gears, transmission_type, engine_size, fuel_type, cylinders, fuel_consumption_comb):

    loaded_model = joblib.load('C:/Users/hempr/Downloads/fedex-main (5)/fedex-main (4)/fedex-main/fedex-main/model_final.pkl')


    transmission_type_mapping = {'A': 0, 'AM': 1, 'AS': 2, 'AV': 3, 'M': 4}
    fuel_type_mapping = {'D': 0, 'E': 1, 'N': 2, 'X': 3, 'Z': 4}

    # Get encoded values from user input
    transmission_type_encoded = transmission_type_mapping.get(transmission_type)
    fuel_type_encoded = fuel_type_mapping.get(fuel_type)
    # Create input array for the model
    input_data = [[num_gears, transmission_type_encoded, engine_size, fuel_type_encoded, cylinders, fuel_consumption_comb]]
    input_data = pd.DataFrame(input_data, columns=['Number of Gears', 'Transmission Type', 'Engine Size', 'Fuel Type', 'Cylinders', 'Fuel Consumption Comb'])

    # Make prediction
    prediction = loaded_model.predict(input_data)

    # Print prediction
    print("Predicted CO2 Emissions:", prediction[0])
    return prediction[0]


# Modified version of get_weather_data with rate-limiting
def get_weather_data(coords, retries=5, delay=1):
    weather_url = "https://api.weatherbit.io/v2.0/forecast/daily"
    params = {
        "lat": coords[0],
        "lon": coords[1],
        "key": WEATHERBIT_API_KEY,
        "days": 1  # Fetch the next 1 day of forecast
    }

    for attempt in range(retries):
        try:
            response = requests.get(weather_url, params=params)
            response.raise_for_status()  # Raise exception for 4xx or 5xx responses

            data = response.json()
            if "data" in data:
                weather_info = []
                for forecast in data["data"]:
                    timestamp = forecast["datetime"]
                    temperature = forecast["temp"]
                    rain = forecast.get("precip", 0)  # Precipitation in mm
                    rain_percentage = (rain / 10) * 100  # Approximation for rain percentage
                    weather_info.append({
                        "timestamp": timestamp,
                        "temperature": temperature,
                        "rain_percentage": rain_percentage  # Convert rain to percentage
                    })
                return weather_info
            else:
                print("No weather data found.")
                return None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Too many requests
                print(f"Rate limited. Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= 2  # Exponentially increase delay
            else:
                print(f"Error fetching weather data: {e}")
                return None

    print("Exceeded retry attempts.")
    return None

"""def get_weather_data(coords):
    weather_url = "https://api.weatherbit.io/v2.0/forecast/daily"
    params = {
        "lat": coords[0],
        "lon": coords[1],
        "key": WEATHERBIT_API_KEY,
        "days": 1  # Fetch the next 2 days of forecast
    }
    try:
        response = requests.get(weather_url, params=params)
        response.raise_for_status()  # Raise exception for 4xx or 5xx responses
        data = response.json()
        if "data" in data:
            weather_info = []
            for forecast in data["data"]:
                timestamp = forecast["datetime"]
                temperature = forecast["temp"]
                rain = forecast.get("precip", 0)  # Precipitation in mm
                rain_percentage = (rain / 10) * 100  # Approximation for rain percentage
                weather_info.append({
                    "timestamp": timestamp,
                    "temperature": temperature,
                    "rain_percentage": rain_percentage  # Convert rain to percentage
                })
            return weather_info
        else:
            print("No weather data found.")
            return None
    except Exception as e:
        print(f"Error fetching weather data: {e}")
        return None"""

weather_cache = {}

def get_weather_data_cached(coords):
    if coords in weather_cache:
        return weather_cache[coords]

    weather_data = get_weather_data(coords)  # Original API call
    weather_cache[coords] = weather_data
    return weather_data


# Function to calculate rain delay based on probability
def calculate_rain_delay(rain_probability, base_delay=8):
    """
    Calculate delay based on rain probability.
    - base_delay: Base delay in minutes for rain > 50%.
    - Returns additional delay in minutes.
    """
    if rain_probability > 0.5:
        if rain_probability > 0.9:
            print("Plane stalled in sky due to heavy bad weather")
            return base_delay * 5  # Severe rain delay
        elif rain_probability > 0.8:
            print("Plane stalled in sky due to heavy bad weather")
            return base_delay * 4
        elif rain_probability > 0.7:
            print("Plane slowing down due to bad weather")
            return base_delay * 3
        elif rain_probability > 0.6:
            print("Plane slowing down due to bad weather")
            return base_delay * 2
        else:  # 0.5 < probability <= 0.6
            print("Plane slightly taking rounds due to bad weather")
            return base_delay
    return 0  # No delay if rain probability <= 0.5


# Function to calculate route using OSRM
def get_osrm_route(start_coords, end_coords):
    osrm_url = f"http://router.project-osrm.org/route/v1/driving/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&alternatives=true"
    try:
        response = requests.get(osrm_url)
        response.raise_for_status()
        data = response.json()
        if data.get("routes"):
            routes = []
            for route in data["routes"]:
                geometry = route["geometry"]
                decoded_geometry = decode(geometry)  # Decode polyline to lat-lon pairs
                distance = route["distance"] / 1000  # Convert meters to kilometers
                duration = route["duration"] / 60  # Convert seconds to minutes
                routes.append((decoded_geometry, distance, duration))
            return routes
        else:
            print("No routes found from OSRM.")
            return []
    except Exception as e:
        print(f"Error fetching route from OSRM: {e}")
        return []
def get_osrm_walking_route(start_coords, end_coords):
    osrm_url = f"https://routing.openstreetmap.de/routed-foot/route/v1/foot/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&alternatives=true&continue_straight=false&annotations=true&steps=true"
    try:
        response = requests.get(osrm_url)
        response.raise_for_status()
        data = response.json()
        if data.get("routes"):
            routes = []
            for route in data["routes"]:
                geometry = route["geometry"]
                decoded_geometry = decode(geometry)  # Decode polyline to lat-lon pairs
                distance = route["distance"] / 1000  # Convert meters to kilometers
                duration = route["duration"] / 60  # Convert seconds to minutes
                routes.append((decoded_geometry, distance, duration))
            return routes
        else:
            print("No walking routes found from OSRM.")
            return []
    except Exception as e:
        print(f"Error fetching walking route from OSRM: {e}")
        return []
def get_osrm_bike_route(start_coords, end_coords):
    osrm_url = f"https://routing.openstreetmap.de/routed-bike/route/v1/bike/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&alternatives=true&continue_straight=false&annotations=true&steps=true"
    try:
        response = requests.get(osrm_url)
        response.raise_for_status()
        data = response.json()
        if data.get("routes"):
            routes = []
            for route in data["routes"]:
                geometry = route["geometry"]
                decoded_geometry = decode(geometry)  # Decode polyline to lat-lon pairs
                distance = route["distance"] / 1000  # Convert meters to kilometers
                duration = route["duration"] / 60  # Convert seconds to minutes
                routes.append((decoded_geometry, distance, duration))
            return routes
        else:
            print("No walking routes found from OSRM.")
            return []
    except Exception as e:
        print(f"Error fetching walking route from OSRM: {e}")
        return []
# Function to fetch traffic flow data from TomTom
def get_traffic_color(coords):
    traffic_url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
    params = {
        "key": TOMTOM_API_KEY,
        "point": f"{coords[0]},{coords[1]}"
    }
    try:
        response = requests.get(traffic_url, params=params)
        response.raise_for_status()
        data = response.json()
        if "flowSegmentData" in data:
            free_flow_speed = data["flowSegmentData"]["freeFlowSpeed"]
            current_speed = data["flowSegmentData"]["currentSpeed"]
            congestion = free_flow_speed - current_speed
            # Determine color based on congestion
            if congestion > 15:
                return "red"
            elif 5 < congestion <= 15:
                return "orange"
            else:
                return "blue"
        return "blue"  # Default color if no data
    except Exception as e:
        print(f"Error fetching traffic data: {e}")
        return "blue"  # Default color if error occurs

# Function to find the nearest airport to given coordinates
def find_nearest_airport(coords, airport_data):
    airport_data["distance"] = airport_data.apply(
        lambda row: geodesic((row["latitude_deg"], row["longitude_deg"]), coords).km, axis=1
    )
    nearest_airport = airport_data.loc[airport_data["distance"].idxmin()]
    return nearest_airport["name"], (nearest_airport["latitude_deg"], nearest_airport["longitude_deg"]), nearest_airport["distance"]

def get_vehicle_type():
    """
    Prompt the user for a vehicle type and return it.
    The user can choose between different vehicle types.
    """
    valid_vehicle_types = [
        "bike", "cargo_van", "minivan", "small_truck", "heavy_duty_truck", "18_wheeler", "car", "plane"
    ]

    # Prompt the user to select a vehicle type
    vehicle_type = input("Enter vehicle type (bike, cargo_van, minivan, small_truck, heavy_duty_truck, 18_wheeler, car, plane): ").lower()

    # Validate the user input
    while vehicle_type not in valid_vehicle_types:
        print("Invalid vehicle type. Please select from the following options:")
        print(", ".join(valid_vehicle_types))
        vehicle_type = input("Enter vehicle type: ").lower()

    return vehicle_type
# Function to display the route with traffic data on a map

def display_route_with_traffic(route_map, routes, traffic_colors, air_segments, location_airport_segments, vehicle_emission,tf,weather_info=None):
    # Add road segments
    total_co2_emission11 = 0.0
    for route, colors in zip(routes, traffic_colors):
        for i in range(len(route) - 1):
            segment_coords = [route[i], route[i + 1]]
            segment_distance = geodesic(route[i], route[i + 1]).km
            #vehicle_type=vehicle
            # Check weather and adjust color (green for good, red for heavy rain)
            if weather_info:
                rain_percentage = weather_info["rain_percentage"]
                line_color = 'green' if rain_percentage < 0.4 else 'red'
            else:
                line_color = colors[i]  # Default to traffic color if no weather data
            
            co2_emissions = calculate_co2_emissions1(segment_distance, tf, vehicle_emission)
            total_co2_emission11 +=  co2_emissions
            print(f"CO2 emissions for this route segment: {co2_emissions:.2f} kg")
            


            folium.PolyLine(
                locations=segment_coords, color=line_color, weight=5, opacity=0.7
            ).add_to(route_map)
          

    # Add air travel segments
    for air_segment in air_segments:
        folium.PolyLine(
            locations=air_segment, color="red", weight=5, opacity=0.7, tooltip="Air Travel"
        ).add_to(route_map)

    # Add location-to-airport connections
    for segment in location_airport_segments:
        folium.PolyLine(
            locations=segment["coords"], color="green", weight=2, opacity=0.7, tooltip=f"{segment['label']}"
        ).add_to(route_map)
    return total_co2_emission11

def traffic_factor(traffic_colors):
    total_r,total_o,total_b=0,0,0
    length = len(traffic_colors)
    for color in traffic_colors:
        if color=="red":
            total_r+=1
        elif color=="orange":
            total_o+=1
        elif color=="blue":
            total_b+=1
    return (total_r*2.5 + total_o*1.5+total_b*1)/length





def calculate_co2_emissions(distance_km,traffic_factor,vehicle_type="car"):
    print(vehicle_type)
    """
    Calculate CO2 emissions based on the distance and vehicle type.

    Args:
    - distance_km (float): The distance in kilometers.
    - vehicle_type (str): The type of vehicle.

    Returns:
    - float: The CO2 emissions in kilograms.
    """
    # CO2 emission factors for different vehicle types (in kg per km)
    vehicle_emission_factors = {
        "bike": 0.005,  # Minimal emissions for a bike
        "cargo_van": 0.295,  # Approx 295g CO2 per km for cargo van
        "minivan": 0.198,  # Approx 198g CO2 per km for minivan
        "truck": 0.311,  # Approx 311g CO2 per km for small truck
        "heavy_duty_truck": 0.768,  # Approx 768g CO2 per km for heavy-duty truck
        "18_wheeler": 1.0,  # Approx 1000g CO2 per km for an 18-wheeler
        "car": 0.120,  # Approx 120g CO2 per km for a car
        "plane": 2.5,  # Approx 2.5 kg CO2 per km for the entire plane
    }


    #if vehicle_type not in vehicle_emission_factors:
    #   raise ValueError(f"Unsupported vehicle type: {vehicle_type}")

    co2_per_km = vehicle_emission_factors[vehicle_type]
    co2_emissions = distance_km * co2_per_km * traffic_factor # CO2 in kilograms
    return co2_emissions
def calculate_co2_emissions1(distance,traffic_factor,vehicle_emission):
    co2_emissions = 0.0
    co2_emissions = distance * vehicle_emission * traffic_factor*0.001
    return co2_emissions

# def get_vehicle_type(cargo_weight):
#     if cargo_weight < 10:
#         v = input("Motocycle/car/minivan/truck/18-wheeler")
#     elif cargo_weight < 50:
#         v = input("car/minivan/truck/18-wheeler")
#     elif cargo_weight < 100:
#         v = input("minivan/truck/18-wheeler")
#     elif cargo_weight < 500:
#         v = input("truck/18-wheeler")
#     else:
#         v = "18_wheeler"
#     return v

def get_vehicle_airports(cargo_weight):
    if cargo_weight < 10:
        return "motorcycle"
    elif cargo_weight < 50:
        return "car"
    elif cargo_weight < 100:
        return "minivan"
    elif cargo_weight < 500:
        return "truck"
    else:

        return "18_Wheeler"
def calculate_co2_emissions_air(distance):
    emissions = distance*2.5
    return emissions


# Haversine formula to calculate the great-circle distance between two points
def haversine(coords1,coords2):
    R = 6371  # Earth radius in kilometers
    lat1, lon1, lat2, lon2 = map(np.radians, [coords1[0], coords1[1], coords2[0], coords2[1]])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0)*2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0)*2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

# Function to find the nearest airport
va=[]
def find_next_airport(coords, df,va,tolerance=0.01):
    """
    Finds the nearest airport to the specified coordinates.

    Parameters:
        lat (float): Latitude of the input location.
        lon (float): Longitude of the input location.
        df (DataFrame): The dataset containing airport information.
        tolerance (float): A small value to exclude the input airport based on coordinates.

    Returns:
        dict: Information about the nearest airport.
    """
    # Calculate distances to all airports
    distances = haversine(coords, (df["latitude_deg"], df["longitude_deg"]))

    # Exclude the input airport by ensuring a tolerance for coordinates
    same_airport_mask = (
        (np.abs(df["latitude_deg"] - coords[0]) < tolerance) &
        (np.abs(df["longitude_deg"] - coords[1]) < tolerance)
    )
    distances[same_airport_mask] = np.inf  # Set distance to self as infinity

    for tup in va:
      visited_airport_mask = (
        (np.abs(df["latitude_deg"] - coords[0]) < tolerance) &
        (np.abs(df["longitude_deg"] - coords[1]) < tolerance)
    )
    distances[visited_airport_mask] = np.inf


    # Find the index of the nearest airport
    nearest_index = distances.idxmin()
    nearest_airport = df.loc[nearest_index]

    return nearest_airport["name"],  (nearest_airport["latitude_deg"], nearest_airport["longitude_deg"])

def generate_points_between_coordinates(coord1, coord2, num_points=8):
    """
    Generate equally spaced points between two coordinates.

    :param coord1: Tuple (x1, y1) representing the starting coordinate.
    :param coord2: Tuple (x2, y2) representing the ending coordinate.
    :param num_points: Number of points to generate between the coordinates.
    :return: List of tuples representing the generated points.
    """
    x1, y1 = coord1
    x2, y2 = coord2
    return [
        (x1 + i * (x2 - x1) / (num_points + 1), y1 + i * (y2 - y1) / (num_points + 1))
        for i in range(1, num_points + 1)
    ]
def get_aqi_for_location(tuple1, api_key):
    url = f"http://api.waqi.info/feed/geo:{tuple1[0]};{tuple1[1]}/?token={api_key}"
    response = requests.get(url)
    data = response.json()
    if data['status'] == 'ok':
        return data['data']['aqi']  # Return the AQI value
    else:
        return None
def smooth_reroute_path(start, end, affected_points, reroute_offset=0.3):
    waypoints = generate_waypoints(start, end, num_points=20)

    # Separate latitudes and longitudes
    lats, lons = zip(*waypoints)

    # Apply offset to affected waypoints
    for i, point in enumerate(waypoints):
        if point in affected_points:
            lats = list(lats)
            lons = list(lons)
            lats[i] += reroute_offset  # Adjust latitude smoothly
            lons[i] += reroute_offset / 2  # Adjust longitude smoothly

    # Use interpolation to create a smooth reroute
    interp_lat = interp1d(range(len(lats)), lats, kind='cubic')
    interp_lon = interp1d(range(len(lons)), lons, kind='cubic')

    smooth_waypoints = list(zip(interp_lat(np.linspace(0, len(lats) - 1, len(lats))),
                                interp_lon(np.linspace(0, len(lons) - 1, len(lons)))))

    return smooth_waypoints

# Function to reroute air path based on weather conditions
def reroute_air_path(start, end, api_key):
    waypoints = generate_points_between_coordinates(start, end, num_points=8)
    safe_waypoints = []
    affected_points = []

    for wp in waypoints:
        weather_inf = get_weather_data(wp)
        if weather_inf:
          for forecast in weather_inf:
            rain_probability = forecast["rain_percentage"] / 100

        if rain_probability is not None and rain_probability >  0.1:
            print(f"High rain detected at {wp} ({rain_probability}%), rerouting...")
            affected_points.append(wp)
        else:
            safe_waypoints.append(wp)

    # Smooth the rerouted path if bad weather is found
    if affected_points:
        return smooth_reroute_path(start, end, affected_points)
    else:
        return waypoints

# Function to plot the route on a Folium map


# Function to get coordinates of a city using Geopy
def generate_waypoints(start, end, num_points=10):
    lat_points = np.linspace(start[0], end[0], num_points)
    lon_points = np.linspace(start[1], end[1], num_points)
    return list(zip(lat_points, lon_points))
# Function to calculate rain delay based on probability
def calculate_rain_delay(rain_probability, base_delay=8):
    if rain_probability > 0.5:
        if rain_probability > 0.9:
            print("Heavy rain detected.")
            return base_delay * 5
        elif rain_probability > 0.8:
            return base_delay * 4
        elif rain_probability > 0.7:
            return base_delay * 3
        elif rain_probability > 0.6:
            return base_delay * 2
        else:
            return base_delay
    return 0

# Function to calculate CO2 emissions
def calculate_co2_emissions(distance_km, traffic_factor, vehicle_type="car"):
    vehicle_emission_factors = {
        "bike": 0.005,
        "cargo_van": 0.295,
        "minivan": 0.198,
        "small_truck": 0.311,
        "heavy_duty_truck": 0.768,
        "18_wheeler": 1.0,
        "car": 0.120,
        "plane": 2.5,
    }

    co2_per_km = vehicle_emission_factors.get(vehicle_type, 0.120)  # Default to car if not found
    co2_emissions = distance_km * co2_per_km * traffic_factor
    return co2_emissions

# Function to get OSRM route
def get_osrm_route(start_coords, end_coords):
    osrm_url = f"http://router.project-osrm.org/route/v1/driving/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&alternatives=true"
    try:
        response = requests.get(osrm_url)
        response.raise_for_status()
        data = response.json()
        if data.get("routes"):
            routes = []
            for route in data["routes"]:
                geometry = route["geometry"]
                decoded_geometry = decode(geometry)
                distance = route["distance"] / 1000
                duration = route["duration"] / 60
                routes.append((decoded_geometry, distance, duration))
            return routes
        else:
            print("No routes found from OSRM.")
            return []
    except Exception as e:
        print(f"Error fetching route from OSRM: {e}")
        return []

# Function to plan route
@app.route('/plan_route', methods=['POST'])
def plan_route():
    try:
        start_city = request.form['startLocation']
        end_city = request.form['endLocation']
        cargo_weight = 100

        stop_loc =''
        vehicle_input = 'truck'
        num_gears_start = 4
        transmission_type_start = 'A'
        engine_size_start =2.5
        fuel_type_start = 'X'
        cylinders_start = 4
        fuel_consumption_start =8
        air_travel_start = 'No'

        # Collect stops
        stops = []
        stop_index = 0
        

        # Call the main function with the provided parameters
        route_map = main(start_city, end_city, stop_loc, vehicle_input, stops, cargo_weight, 
                          num_gears_start, transmission_type_start, 
                          engine_size_start, fuel_type_start, 
                          cylinders_start, fuel_consumption_start, 
                          air_travel_start)

        if route_map:
            route_map_file = "route_with_traffic_and_weather.html"
            route_map.save(route_map_file)
            return jsonify(success=True, file=route_map_file)
        else:
            return jsonify(success=False, message="Error generating route"), 500
    except Exception as e:
        return jsonify(success=False, message=f"Error generating route: {str(e)}"), 500

@app.route('/final_page')
def final_page():
    return render_template('final_page.html')

@app.route("/route")
def route_page():
    return render_template("idummy.html")

# Main function
def main(start_city, end_city, stop_loc, vehicle_input,stops_data, cargo_weight, num_gears, transmission_type, engine_size, fuel_type, cylinders, fuel_consumption_comb, air_travel_start):
    # Input start, destination, and optional stops
    html_content="""<html>
    <head><title>Outputs</title></head>
    <body>
    <h1>Output for routes:</h1>"""
    stops = stop_loc.split(",")
    vehicle_type_road = vehicle_input
    co2_for_vehicle = predict_co2_emissions(num_gears, transmission_type, engine_size, fuel_type, cylinders, fuel_consumption_comb)


    stops = [stop.strip() for stop in stops if stop.strip()]

    start_coords = get_coordinates(start_city)
    end_coords = get_coordinates(end_city)
    stop_coords = [get_coordinates(stop) for stop in stops]


    # Load airport data for air travel logic
    airport_data = pd.read_csv("C:/Users/hempr/Downloads/fedex-main (5)/fedex-main (4)/fedex-main/fedex-main/airports.csv")
    airport_data = airport_data[airport_data['type'].str.contains("airport", case=False)]


    if start_coords and end_coords and all(stop_coords):
        # Combine all points into a full route (start -> stops -> end)
        full_route = [start_coords] + stop_coords + [end_coords]
        air_segments = []
        location_airport_segments = []

        # Initialize map
        route_map = folium.Map(location=start_coords, zoom_start=7)
        
        # Iterate through each segment in the route
        N=1
        U=1
        if vehicle_type_road == "car" or vehicle_type_road == "motorcycle":
            U=1
        elif vehicle_type_road == "minivan":
            U=2
        else:
            U=3

        for i in range(len(full_route) - 1):
            segment_start = full_route[i]
            segment_end = full_route[i + 1]
            if U==3:
                all_routes = get_osrm_route(segment_start, segment_end)
            elif U==2:
                all_routes = get_osrm_bike_route(segment_start, segment_end)
            else:
                all_routes = get_osrm_walking_route(segment_start, segment_end)

            
            if all_routes:
                
                x=1
                print(N)
                if N > 1:
                    if N-1 < len(stops_data):  # Check if N-1 is within the valid range
                        print("Getting inputs for stop", N)
                        stop_name = stops_data[N-1].get("location", "Unknown")
                        drop_off = stops_data[N-1].get('drop_off_weight', 0)

                        try:
                            idropoff = int(drop_off)
                            icargo_weight -= idropoff
                        except ValueError:
                            idropoff = 0

                        vehicle_type_road = stops_data['vehicle_input']

                        num_gears = stops_data[N-1].get('num_gears', num_gears)
                        transmission_type = stops_data[N-1].get('transmission_type', transmission_type)
                        engine_size = stops_data[N-1].get('engine_size', engine_size)
                        fuel_type = stops_data[N-1].get('fuel_type', fuel_type)
                        cylinders = stops_data[N-1].get('cylinders', cylinders)
                        fuel_consumption_comb = stops_data[N-1].get('fuel_consumption_comb', fuel_consumption_comb)
                        co2_for_vehicle = predict_co2_emissions(
                            num_gears, transmission_type, engine_size, fuel_type, cylinders, fuel_consumption_comb
                        )
                        N += 1
                        print("Updated N to", N)
                    else:
                        print(f"Warning: No data for stop {N}, skipping.")
                        N += 1  # Increment N to continue the loop
                else:
                    print("Incrementing N")
                    N += 1
                    print("Incremented N to", N)
                for idx, (decoded_geometry, _, _) in enumerate(all_routes):

                    """print(n)
                    if n>1:
                      drop_off = input("Enter drop off at segment 1")
                      idropoff = int(drop_off)
                      icargo_weight -= idropoff
                      vehicle_type_road = get_vehicle_type(icargo_weight)
                      n+=1
                    if n==1:
                      n+=1"""
                    road_time=0.0


                  

                    print(f"Route {idx + 1} for Segment {i + 1}:")
                    segment_distance = geodesic(segment_start, segment_end).km
                    #print(f"Route Distance{segment_distance:.2f}")
                    if U==3:
                      if vehicle_type_road == "18_wheeler":

                        road_time = segment_distance/35
                      else:
                        road_time = segment_distance/45

                    elif U==2:
                        road_time = segment_distance/60
                    else:
                        road_time = segment_distance/70
                    #print(f"Road Time without delay: {road_time:.2f} hrs")



                    if segment_distance > 300 and air_travel_start=="yes":
                        air_emssions = calculate_co2_emissions_air(segment_distance)
                        print(f"CO2 emissions for this route segment: {air_emssions:.2f} kg")
                        total_co2_emissions += air_emssions
                        # Nearest airports for air travel
                        start_airport_name, start_airport_coords, _ = find_nearest_airport(segment_start, airport_data)
                        end_airport_name, end_airport_coords, _ = find_nearest_airport(segment_end, airport_data)
                        c1=get_weather_data(start_airport_coords)
                        c2=get_weather_data(end_airport_coords)
                        va.append(start_airport_coords)
                        va.append(end_airport_coords)



                        while c1[0]["rain_percentage"] > 0.5 or c2[0]["rain_percentage"] > 0.5:

                            print(c1)
                            print(c2)

                            if c1[0]["rain_percentage"] > 0.1:
                              na1,c11=find_next_airport(start_airport_coords,airport_data,va)
                              start_airport_name, start_airport_coords, _ = find_nearest_airport(c11, airport_data)
                              va.append(start_airport_coords)
                            if c2[0]["rain_percentage"] > 0.1:
                              na2,c22=find_next_airport(end_airport_coords,airport_data,va)
                              end_airport_name, end_airport_coords, _ = find_nearest_airport(c22, airport_data,)
                              va.append(end_airport_coords)

                            c1=get_weather_data(start_airport_coords)
                            c2=get_weather_data(end_airport_coords)
                        print(f"Air Travel: {start_airport_name} -> {end_airport_name}")

                        # Flight segment
                        air_segments.append([start_airport_coords, end_airport_coords])
                        flight_distance = geodesic(start_airport_coords, end_airport_coords).km

                        # Calculate flight time
                        flight_time = (flight_distance / 400) * 60  # Assuming average flight speed is 800 km/h

                        # Road segments to/from airports
                        road_to_airport, road_to_airport_distance, road_to_airport_duration = get_osrm_route(segment_start, start_airport_coords)[0]
                        road_from_airport, road_from_airport_distance, road_from_airport_duration = get_osrm_route(end_airport_coords, segment_end)[0]
                        print("USED AIR TRAVEL CALCULATING UR VEHICLE FOR ROAD SEGMENT BASED ON CARGO WEIGHT")
                        vehiclee = get_vehicle_airports(icargo_weight)
                        print(vehiclee)
                        print("USED")

                        # Total times
                        total_road_time = road_to_airport_duration + road_from_airport_duration
                        total_air_time = flight_time

                        # Rain delay for air route
                        #sampled_indices = np.linspace(0, len(air_segments[-1]) - 1, 2, dtype=int)
                        #sampled_air_points = [air_segments[-1][i] for i in sampled_indices]
                        #air_weather_data = [get_weather_data_cached(point) for point in sampled_air_points]
                        tt=generate_points_between_coordinates(start_airport_coords, end_airport_coords, num_points=8)

                        tt1=reroute_air_path(start_airport_coords, end_airport_coords, WEATHERBIT_API_KEY)
                        tt=tt1


                        air_weather_data = [get_weather_data_cached(point) for point in tt]
                        air_rain_delay = 0

                        for point, weather in zip(tt, air_weather_data):
                            if weather:
                                for forecast in weather:
                                    rain_probability = forecast["rain_percentage"] / 100  # Convert to decimal
                                    air_rain_delay += calculate_rain_delay(rain_probability)
                                    print(f"Air Route Weather - Timestamp: {forecast['timestamp']}, "
                                          f"Coords: {point}, Temp: {forecast['temperature']}°C, "
                                          f"Rain Probability: {forecast['rain_percentage']}%, "
                                          f"Added Delay: {calculate_rain_delay(rain_probability)} minutes")


                        # Rain delay for road routes to/from airports
                        road_rain_delay = 0

                        for road_point in road_to_airport + road_from_airport:
                            weather = get_weather_data(road_point)
                            if weather:
                                for forecast in weather:
                                    rain_probability = forecast["rain_percentage"] / 100  # Convert to decimal
                                    road_rain_delay += calculate_rain_delay(rain_probability)

                        # Total travel time
                        total_travel_time = total_road_time + total_air_time + air_rain_delay + road_rain_delay

                        print(f"Flight Distance: {flight_distance:.2f} km, Flight Time: {flight_time:.2f} minutes")
                        print(f"Road Distance to/from Airports: {road_to_airport_distance + road_from_airport_distance:.2f} km")
                        print(f"Total Ground Travel Time: {total_road_time:.2f} minutes")
                        #print(f"Total Rain Delay (Air + Ground): {air_rain_delay + road_rain_delay:.2f} minutes")
                        print(f"Total Travel Time (Including Delays): {total_travel_time:.2f} minutes")
                        
                        html_content+=f"<p>Flight Distance: {flight_distance:.2f} km, Flight Time: {flight_time:.2f} minutes<br>Road Distance to/from Airports: {road_to_airport_distance + road_from_airport_distance:.2f} km<br>Total Ground Travel Time: {total_road_time:.2f} minutes<br>Total Travel Time (Including Delays): {total_travel_time:.2f} minuutes<br></p><br><br>"

                        # Display on map
                        traffic_colors = [get_traffic_color(point) for point in road_to_airport + road_from_airport]
                        tf = traffic_factor(traffic_colors)
                        display_route_with_traffic(
                            route_map,
                            [road_to_airport + road_from_airport],
                            [traffic_colors],
                            air_segments,
                            location_airport_segments,
                            vehiclee,
                            tf
                        )
                    else:

                        # Continue with normal driving route
                        for idx, (decoded_geometry, _, _) in enumerate(all_routes):
                            print(f"Route {idx + 1} for Segment {i + 1}:")
                            sampled_indices = np.linspace(0, len(decoded_geometry) - 1, 10, dtype=int)
                            sampled_points = [decoded_geometry[i] for i in sampled_indices]
                            segment_distance_1 = geodesic(segment_start, segment_end).km


                            # Fetch weather data for sampled points
                            road_time_rain = 0
                            for point in sampled_points:

                                weather_info = get_weather_data(point)

                                if weather_info:
                                    for weather in weather_info:
                                        rain_percentage = weather["rain_percentage"]
                                        temperature = weather["temperature"]
                                        timestamp = weather["timestamp"]

                                        print(f"Timestamp: {timestamp}")
                                        print(f"Coordinates: {point}")
                                        print(f"Temperature: {temperature}°C")
                                        print(f"Rain Probability: {rain_percentage}%")
                                        road_time_rain += calculate_rain_delay(rain_percentage)
                                        if rain_percentage > 40:
                                            print("WARNING: Heavy rain expected! Possible delays.")
                                            x+=1

                                    print("-" * 50)
                                else:
                                    print(f"No weather data available for point {point}.")
                                    print("-" * 50)
                            road_time = road_time + road_time_rain

                            sampled_indices = np.linspace(0, len(decoded_geometry) - 1, 100, dtype=int)
                            road_routes_1 = [decoded_geometry[i] for i in sampled_indices]
                            avg_air=0
                            total_air=0
                            for(point) in sampled_points:
                                air_info = get_aqi_for_location(point, "9e51dee0e109c3bb54c7c76d568f34440cdc4125")
                                total_air+=air_info
                            avg_air=total_air/len(sampled_points)
                            print(avg_air)
                            
                            #road_routes, road_routes_distance, road_routes_duration = get_osrm_route(segment_start, segment_end)[0]
                            sampled_indices = np.linspace(0, len(decoded_geometry) - 1, 60, dtype=int)
                            road_routes = [decoded_geometry[i] for i in sampled_indices]
                            # Get traffic data for sampled points along the route
                            traffic_colors = [get_traffic_color(point) for point in road_routes]
                            tf = traffic_factor(traffic_colors)
                            

                            # Add route to map
                            road_emissions = display_route_with_traffic(route_map, [road_routes], [traffic_colors], air_segments, location_airport_segments,co2_for_vehicle,tf)
                            road_time = road_time*tf

                            print(f"Total road time: {road_time:.2f} hrs")
                            print(f"CO2 emissions for this route segment: {road_emissions:.2f} kg")
                            
                            html_content +=f"""<p>Route {idx + 1} for Segment {i + 1}:<br>
                                    CO2 Emissions: {road_emissions:.2f} kg<br>
                                    Road_time: {road_time:.2f} hrs<br>
                                    Segment_distance: {segment_distance_1:.2f}<br></p><br><br>"""
                i+=1        
                            
                                    





        return route_map

    else:
        print("Error in getting coordinates for cities or stops.")
    html_content+="</body></html>"

    html_file_path = "route_output.html"
    with open(html_file_path, 'w') as file:
        file.write(html_content)

    print("HTML file has been generated.")

    # Open the HTML file in the default web browser
    if os.name == 'nt':  # For Windows
        os.startfile(html_file_path)
    elif os.name == 'posix':  # For macOS and Linux
        webbrowser.open('file://' + os.path.realpath(html_file_path))

from flask import send_from_directory
@app.route('/route_map/<path:filename>')
def serve_route_map(filename):
    return send_from_directory(os.getcwd(), filename)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    threading.Thread(target=auto_release_slots, daemon=True).start()

    app.run(debug=True)