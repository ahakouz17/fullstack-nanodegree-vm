from flask import Flask, url_for, render_template, request
from flask import session as login_session
from flask import make_response, flash, redirect, jsonify

from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from database_setup import Base, Category, Item, User

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError

import httplib2
import json
import random
import string
import requests

app = Flask(__name__)

# Connect to Database and create database session
engine = create_engine('sqlite:///itemcatalog.db',
                       connect_args={'check_same_thread': False})
Base.metadata.bind = engine
DBSession = sessionmaker(bind=engine)
session = DBSession()

# initialize google sign in info
CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Item Catalog"


# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(
        string.ascii_uppercase + string.digits) for x in range(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)

# google sign-in functions
@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Obtain authorization code
    request.get_data()
    code = request.data.decode('utf-8')

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    # Submit request, parse response - Python3 compatible
    h = httplib2.Http()
    response = h.request(url, 'GET')[1]
    str_response = response.decode('utf-8')
    result = json.loads(str_response)

    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']
    login_session['provider'] = 'google'
    # see if user exists, if it doesn't make a new one
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    # Show the logged in user info and picture, then redirect to the main page
    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' "> '
    flash("you are now logged in as %s" % login_session['username'])
    return output


# disconnect the google-logged-in user (if exists)
@app.route('/gdisconnect')
def gdisconnect():
    # Only disconnect a connected user.
    access_token = login_session.get('access_token')
    if access_token is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    if result['status'] == '200':
        # Reset the user's sesson.
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']

        flash('Successfully disconnected.')
        return redirect(url_for("showCatalog"))
    else:
        # For whatever reason, the given token was invalid.
        response = make_response(
            json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


# the main page showing the categories, and the latest items
# -1 is passed as the category_name to showCategory, which means that
# no category is selected yet (i.e., show latest items)
@app.route('/')
@app.route('/catalog')
def showCatalog():
    return showCategory(-1)


# Shows the list of items of the selected category with 'category_name'
@app.route('/catalog/<string:category_name>/items')
def showCategory(category_name):
    categories = session.query(Category)
    selected_category = -1
    # no category is selected, show the latest 10 item which were added
    if category_name == -1:
        items = session.query(Item).order_by(desc(Item.date_created))
        if len(items.all()) > 10:
            items = items[:10]
    else:
        selected_category = session.query(
            Category).filter_by(name=category_name).one()
        items = session.query(Item).filter_by(category_id=selected_category.id)

    # get the number of items for each category
    category_counts = {}
    for c in categories:
        count = session.query(Item).filter_by(category_id=c.id).count()
        category_counts[c.id] = count

    if 'username' not in login_session:
        return render_template('publiccatalog.html', categories=categories,
                               latest_items=items,
                               category_counts=category_counts,
                               selected_category=selected_category)
    else:
        return render_template('catalog.html', categories=categories,
                               latest_items=items,
                               category_counts=category_counts,
                               selected_category=selected_category)


# show the page of an item with 'item_name'
@app.route('/catalog/<string:category_name>/<string:item_name>/')
def showItem(category_name, item_name):
    item = session.query(Item).filter_by(title=item_name).one()

    if 'username' not in login_session:
        return render_template('publicitem.html', item=item)
    else:
        return render_template('item.html', item=item)


# shows the page to add new item
@app.route('/catalog/newitem', methods=['GET', 'POST'])
def addNewItem():
    if 'username' not in login_session:
        return redirect('/login')

    if request.method == 'POST':
        newItem = Item(title=request.form['name'],
                       user_id=login_session['user_id'],
                       description=request.form['description'],
                       category_id=request.form['category'])
        session.add(newItem)
        session.commit()
        flash('New Item %s Successfully Created' % newItem.title)
        return redirect(url_for('showCatalog'))
    else:
        # fetch the list of categories for the drop-down list
        categories = session.query(Category).all()
        # render the form for adding a new item
        return render_template('newItem.html',
                               username=login_session['username'],
                               categories=categories)


# shows the page to edit an item
@app.route('/catalog/<string:category_name>/<string:item_name>/edit',
           methods=['GET', 'POST'])
def editItem(category_name, item_name):
    if 'username' not in login_session:
        return redirect('/login')

    category = session.query(Category).filter_by(name=category_name).one()
    item = session.query(Item).filter_by(title=item_name,
                                         category_id=category.id).one()

    # check if the user owns the item he/she is trying to edit
    if item.user_id != login_session['user_id']:
        out = "<script>function myFunction() {"
        out += "alert('You are not authorized to edit this item. "
        out += "Please create your own items in order to edit.');"
        out += "window.location.replace('/catalog')}</script>"
        out += "<body onload='myFunction()''>"
        return out

    if request.method == "POST":
        # uodate the attributes of the item and update the database
        if request.form['name']:
            item.title = request.form['name']
        if request.form['description']:
            item.description = request.form['description']
        if request.form['category']:
            item.category_id = request.form['category']
        session.add(item)
        session.commit()
        flash('Item Successfully Edited %s' % item.title)
        return redirect(url_for('showCatalog'))
    else:
        # render the form for editing an item
        categories = session.query(Category).all()
        return render_template('editItem.html',
                               username=login_session['username'],
                               item=item, categories=categories)


# shows the page to delete an item
@app.route('/catalog/<string:category_name>/<string:item_name>/delete',
           methods=['GET', 'POST'])
def deleteItem(category_name, item_name):
    if 'username' not in login_session:
        return redirect('/login')

    category = session.query(Category).filter_by(name=category_name).one()
    item = session.query(Item).filter_by(title=item_name,
                                         category_id=category.id).one()

    if item.user_id != login_session['user_id']:
        out = "<script>function myFunction() {alert("
        out += "'You are not authorized to delete this item.');"
        out += "window.location.replace('/catalog');"
        out += "}</script><body onload='myFunction()''>"
        return out

    if request.method == "POST":
        session.delete(item)
        session.commit()
        flash('Item Successfully Deleted %s' % item.title)
        return redirect(url_for('showCatalog'))
    else:
        return render_template('deleteItem.html',
                               username=login_session['username'],
                               item=item)


@app.route('/catalog/<string:category_name>/editcategoory',
           methods=['GET', 'POST'])
def editCategory(category_name):
    if 'username' not in login_session:
        return redirect('/login')

    category = session.query(Category).filter_by(name=category_name).one()

    if category.user_id != login_session['user_id']:
        out = "<script>function myFunction() {"
        out += "alert('You are not authorized to edit this category. "
        out += "Please create your own category in order to edit.');"
        out += "window.location.replace('/catalog')}</script>"
        out += "<body onload='myFunction()''>"
        return out

    if request.method == 'POST':
        # uodate the attributes of the category and update the database
        if request.form['name']:
            category.name = request.form['name']
        session.add(category)
        session.commit()
        flash('Category Successfully Edited %s' % category.name)
        return redirect(url_for('showCatalog'))
    else:
        return render_template('editCategory.html', category=category)


@app.route('/catalog/<string:category_name>/deletecategory',
           methods=['GET', 'POST'])
def deleteCategory(category_name):
    if 'username' not in login_session:
        return redirect('/login')

    category = session.query(Category).filter_by(name=category_name).one()

    if category.user_id != login_session['user_id']:
        out = "<script>function myFunction() {alert("
        out += "'You are not authorized to delete this category.');"
        out += "window.location.replace('/catalog');"
        out += "}</script><body onload='myFunction()''>"
        return out

    if request.method == "POST":
        c_items = session.query(Item).filter_by(category_id=category.id).all()
        map(session.delete, c_items)
        session.delete(category)
        session.commit()
        flash('Category Successfully Deleted %s' % category.name)
        return redirect(url_for('showCatalog'))
    else:
        return render_template('deleteCategory.html',
                               username=login_session['username'],
                               category=category)


@app.route('/catalog/newcategory', methods=['GET', 'POST'])
def addNewCategory():
    if 'username' not in login_session:
        return redirect('/login')

    if request.method == 'POST':
        newCategory = Category(name=request.form['name'],
                               user_id=login_session['user_id'])
        session.add(newCategory)
        session.commit()
        flash('New Category %s Successfully Created' % newCategory.name)
        return redirect(url_for('showCatalog'))
    else:
        # render the form for adding a new category
        return render_template('newCategory.html',
                               username=login_session['username'])


@app.route('/catalog.json')
def catalogJSON():
    categories = session.query(Category).all()
    return jsonify(categories=[c.serialize for c in categories])


@app.route('/catalog/<string:category_name>/<string:item_name>.json')
def itemJSON(category_name, item_name):
    category = session.query(Category).filter_by(name=category_name).one()
    item = session.query(Item).filter_by(
        title=item_name, category_id=category.id).one()
    return jsonify(item=item.serialize)


# Helper Functions (Util)
# User Helper Functions


def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except SQLAlchemyError as e:
        print(e)
        return None


if __name__ == '__main__':
    app.secret_key = 'FASFSAFREGW'
    app.debug = True
    app.run(host='0.0.0.0', port=8000)
