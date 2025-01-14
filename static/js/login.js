function start() {
    gapi.load('auth2', function () {
        auth2 = gapi.auth2.init({
            client_id: '<ENTER_YOUR_CLIENT_ID>'
        });
    });
}

$(document).ready(function () {
    $('#signinButton').click(function () {
        function signInCallback(authResult) {
            if (authResult['code']) {
                // Hide the sign-in button now that the user is authorized
                $('#signinContainer').attr('style', 'display:none');
                // Send the one-time-use code to the server, if the server responds, write a 'login successful' message to the web page and then redirect back to the main restaurants page
                $.ajax({
                    type: 'POST',
                    url: '/gconnect?state='+state,
                    processData: false,
                    data: authResult['code'],
                    contentType: 'application/octet-stream; charset=utf-8',
                    success: function (result) {
                        // Handle or verify the server response if necessary.
                        if (result) {
                            $('#result').html('Login Successful!</br>' + result + '</br>Redirecting...');
                            setTimeout(function () {
                                window.location.href = "/";
                            }, 4000);
                        } else if (authResult['error']) {
                            console.log('There was an error: ' + authResult['error']);
                        } else {
                            $('#result').html('Failed to make a server-side call. Check your configuration and console.');
                        }
                    }
                });
            }
        }
        auth2.grantOfflineAccess().then(signInCallback);
    });
});
