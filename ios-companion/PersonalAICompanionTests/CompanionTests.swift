import XCTest
@testable import PersonalAICompanion

final class CompanionTests: XCTestCase {
    func testPairRequestEncodesIOSPlatform() throws {
        let data = try JSONEncoder().encode(PairRequest(token:"token",code:"123456",name:"iPhone",platform:"ios"))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with:data) as? [String:Any])
        XCTAssertEqual(object["platform"] as? String,"ios")
        XCTAssertEqual(object["code"] as? String,"123456")
    }

    func testInsecureTransportHasExplicitSecurityMessage() {
        XCTAssertTrue(CompanionError.insecureTransport.localizedDescription.lowercased().contains("https"))
    }

    func testPairResponseDecodesServerShape() throws {
        let json = #"{"device":{"id":"ios-device"},"bearer_token":"secret"}"#.data(using:.utf8)!
        let value = try JSONDecoder().decode(PairResponse.self,from:json)
        XCTAssertEqual(value.device.id,"ios-device")
        XCTAssertEqual(value.bearer_token,"secret")
    }
}
